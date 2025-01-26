import urllib.request
import zipfile
import io
import xml.etree.ElementTree as ET
from datetime import datetime

def extract_grant_details(xml_content):
    # Parse the XML content
    tree = ET.ElementTree(ET.fromstring(xml_content))
    root = tree.getroot()
    namespace = {'ns': 'http://apply.grants.gov/system/OpportunityDetail-V1.0'}
    opportunities = root.findall('.//ns:OpportunitySynopsisDetail_1_0', namespace)
    today = datetime.utcnow()
    grants = ""
    
    for opp in opportunities:
        opportunity_title = opp.find('ns:OpportunityTitle', namespace)
        description = opp.find('ns:Description', namespace)
        close_date = opp.find('ns:CloseDate', namespace)
        grantor_contact_text = opp.find('ns:GrantorContactText', namespace)
        grantor_contact_email_desc = opp.find('ns:GrantorContactEmailDescription', namespace)
        grantor_contact_email = opp.find('ns:GrantorContactEmail', namespace)

        extracted_data = {
            "Title": opportunity_title.text if opportunity_title is not None else "N/A",
            "Description": description.text if description is not None else "N/A",
            "Close Date": close_date.text if close_date is not None else "N/A",
            "Grantor Contact Text": grantor_contact_text.text if grantor_contact_text is not None else "N/A",
            "Grantor Contact Email Description": grantor_contact_email_desc.text if grantor_contact_email_desc is not None else "N/A",
            "Grantor Contact Email": grantor_contact_email.text if grantor_contact_email is not None else "N/A",
        }

        if close_date is not None:
            try:
                close_date_obj = datetime.strptime(close_date.text.strip(), "%m%d%Y")
                if close_date_obj > today:
                    for key, value in extracted_data.items():
                        grants += f"{key}: {value}\n"
                    grants += "\n"
            except ValueError:
                print(f"Error parsing date '{close_date.text.strip()}'. Skipping...")
    
    return grants

def lambda_handler(event, context):
    date_str = datetime.utcnow().strftime("%Y%m%d")
    file_name = f"GrantsDBExtract{date_str}v2.zip"
    xml_file_name = f"GrantsDBExtract{date_str}.xml"
    url = f"https://prod-grants-gov-chatbot.s3.amazonaws.com/extracts/{file_name}"

    try:
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

        grants = extract_grant_details(xml_content)
        return {
            "statusCode": 200,
            "message": grants
        }

    except Exception as e:
        print(f"Error: {e}")
        return {
            "statusCode": 500,
            "message": str(e),
        }