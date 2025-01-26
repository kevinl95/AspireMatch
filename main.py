import urllib.request
import zipfile
import io
import os
import xml.etree.ElementTree as ET
import json
import gzip
import base64
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
            print(f"File {s3_key} already exists in S3. Skipping extraction.")
            return {
                "statusCode": 200,
                "message": f"File {s3_key} already exists in S3. Skipping extraction.",
                "s3_location": f"https://{s3_bucket}.s3.amazonaws.com/{s3_key}"
            }
        except ClientError as e:
            if e.response['Error']['Code'] != '404':
                raise

        print(f"Downloading file from {url}...")
        with urllib.request.urlopen(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to download file: HTTP {response.status}")
            zip_data = response.read()

        print("Unpacking the zip file...")
        with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
            if xml_file_name not in z.namelist():
                raise Exception(f"Expected XML file {xml_file_name} not found in the archive.")
            xml_content = z.read(xml_file_name)

        namespace = {'ns': 'http://apply.grants.gov/system/OpportunityDetail-V1.0'}
        grants = {}
        today = datetime.utcnow()

        for event, elem in ET.iterparse(xml_content, events=("end",)):
            if elem.tag.endswith('OpportunitySynopsisDetail_1_0'):
                opportunity_title = elem.find('ns:OpportunityTitle', namespace)
                description = elem.find('ns:Description', namespace)
                close_date = elem.find('ns:CloseDate', namespace)
                funding_instrument_type = elem.find('ns:FundingInstrumentType', namespace)
                grantor_contact_text = elem.find('ns:GrantorContactText', namespace)
                grantor_contact_email_desc = elem.find('ns:GrantorContactEmailDescription', namespace)
                grantor_contact_email = elem.find('ns:GrantorContactEmail', namespace)
                # Check if FundingInstrumentType equals "GA"
                if funding_instrument_type is not None and funding_instrument_type.text == "G":
                    # Extract details into a dictionary
                    extracted_data = {
                        "Description": description.text if description is not None else "N/A",
                        "Close Date": close_date.text if close_date is not None else "N/A",
                        "Grantor Contact Text": grantor_contact_text.text if grantor_contact_text is not None else "N/A",
                        "Grantor Contact Email Description": grantor_contact_email_desc.text if grantor_contact_email_desc is not None else "N/A",
                        "Grantor Contact Email": grantor_contact_email.text if grantor_contact_email is not None else "N/A",
                    }

                    # Check if the close date is valid and in the future
                    if close_date is not None:
                        try:
                            close_date_obj = datetime.strptime(close_date.text.strip(), "%m%d%Y")
                            if close_date_obj > today:
                                title = opportunity_title.text if opportunity_title is not None else "Untitled Grant"
                                grants[title] = extracted_data
                        except ValueError:
                            print(f"Error parsing date '{close_date.text.strip()}'. Skipping...")

                # Clear the element from memory
                elem.clear()
        json_grants = json.dumps(grants, indent=4)
        # Save the grants data to S3
        s3_client.put_object(Bucket=s3_bucket, Key=s3_key, Body=json_grants, ContentType='application/json')
        print(f"File {s3_key} saved to S3.")
        # Compress the response
        response_body = json.dumps({
            "statusCode": 200,
            "message": f"File saved to S3 at s3://{s3_bucket}/{s3_key}",
            "s3_location": f"https://{s3_bucket}.s3.amazonaws.com/{s3_key}"
        })
        compressed_response = gzip.compress(response_body.encode('utf-8'))
        encoded_response = base64.b64encode(compressed_response).decode('utf-8')
        
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Content-Encoding": "gzip"
            },
            "body": encoded_response,
            "isBase64Encoded": True
        }

    except Exception as e:
        print(f"Error: {e}")
        return {
            "statusCode": 500,
            "message": str(e),
        }