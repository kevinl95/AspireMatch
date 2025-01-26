import urllib.request
import zipfile
import io
import os
import xml.etree.ElementTree as ET
import json
from datetime import datetime, timezone, timedelta
import boto3
from botocore.exceptions import NoCredentialsError, ClientError

def lambda_handler(event, context):
    eastern = timezone(timedelta(hours=-5))  # US/Eastern is UTC-5
    date_str = datetime.now(eastern).strftime("%Y%m%d")
    file_name = f"GrantsDBExtract{date_str}v2.zip"
    xml_file_name = f"GrantsDBExtract{date_str}v2.xml"
    s3_bucket = os.environ['S3_BUCKET']
    s3_key = f"grants/{date_str}.json"
    url = f"https://prod-grants-gov-chatbot.s3.amazonaws.com/extracts/{file_name}"

    s3_client = boto3.client('s3')

    try:
        # Check if the file already exists in S3
        try:
            s3_client.head_object(Bucket=s3_bucket, Key=s3_key)
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json"
                },
                "body": json.dumps({
                    "message": f"File {s3_key} already exists in S3. Skipping extraction.",
                    "s3_location": f"https://{s3_bucket}.s3.amazonaws.com/{s3_key}"
                })
            }
        except ClientError as e:
            if e.response['Error']['Code'] != '404':
                raise

        try:
            with urllib.request.urlopen(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download file: HTTP {response.status}")
                zip_data = response.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Try yesterday's file
                yesterday_str = (datetime.now(eastern) - timedelta(days=1)).strftime("%Y%m%d")
                file_name = f"GrantsDBExtract{yesterday_str}v2.zip"
                xml_file_name = f"GrantsDBExtract{yesterday_str}v2.xml"
                url = f"https://prod-grants-gov-chatbot.s3.amazonaws.com/extracts/{file_name}"
                with urllib.request.urlopen(url) as response:
                    if response.status != 200:
                        raise Exception(f"Failed to download file: HTTP {response.status}")
                    zip_data = response.read()
            else:
                raise

        with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
            if xml_file_name not in z.namelist():
                raise Exception(f"Expected XML file {xml_file_name} not found in the archive.")
            xml_content = z.read(xml_file_name)

        namespace = {'ns': 'http://apply.grants.gov/system/OpportunityDetail-V1.0'}
        grants = {}
        today = datetime.utcnow()

        for event, elem in ET.iterparse(io.BytesIO(xml_content), events=("end",)):
            if elem.tag.endswith('OpportunitySynopsisDetail_1_0'):
                opportunity_title = elem.find('ns:OpportunityTitle', namespace)
                description = elem.find('ns:Description', namespace)
                close_date = elem.find('ns:CloseDate', namespace)
                funding_instrument_type = elem.find('ns:FundingInstrumentType', namespace)
                additional_info_url = elem.find('ns:AdditionalInformationURL', namespace)
                # Check if FundingInstrumentType equals "GA"
                if funding_instrument_type is not None and funding_instrument_type.text == "G":
                    # Extract details into a dictionary
                    extracted_data = {
                        "Description": description.text if description is not None else "N/A",
                        "Close Date": close_date.text if close_date is not None else "N/A",
                        "Additional Information URL": additional_info_url.text if additional_info_url is not None else "N/A",
                    }

                    # Check if the close date is valid and in the future
                    if close_date is not None:
                        try:
                            close_date_obj = datetime.strptime(close_date.text.strip(), "%m%d%Y")
                            if close_date_obj > today:
                                title = opportunity_title.text if opportunity_title is not None else "Untitled Grant"
                                grants[title] = extracted_data
                        except ValueError:
                            continue

                # Clear the element from memory
                elem.clear()
        json_grants = json.dumps(grants, indent=4)
        # Save the grants data to S3
        s3_client.put_object(Bucket=s3_bucket, Key=s3_key, Body=json_grants, ContentType='application/json')

        # Simplify the response
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "message": f"File saved to S3 at s3://{s3_bucket}/{s3_key}",
                "s3_location": f"https://{s3_bucket}.s3.amazonaws.com/{s3_key}"
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "message": str(e)
            })
        }