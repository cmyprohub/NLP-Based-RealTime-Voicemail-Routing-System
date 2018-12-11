from __future__ import print_function

import json
import urllib
import boto3
from botocore.exceptions import ClientError
import datetime
from datetime import datetime, timedelta, tzinfo
import csv


#Assigning AWS Region and Service details. 
s3 = boto3.client('s3')
comprehend = boto3.client(service_name='comprehend', region_name='us-east-1')
AWS_REGION = "us-east-1"
'''
When a voicemail transcript file file hits the input location (S3 bucket in this case),
the below lambda event handler function executes and does the following:
1. Identifies the file name
2. Opens and reads the content of the Voicemail transcript file
3. Does AWS Comprehend NLP processing steps on the voicemail text to identify dominant language, identify voicemail sentiment, identify key phrases, identify entities
4. Identifies which department should be notified
5. Sends an email alert to the respective department
6. Once done, copies the file to an archive location (another S3 bucket in this case)
7. Deletes the original voicemail text file from the input S3 bucket
'''

#Lambda function - triggers real time as soon as an incoming transcript file comes in
def lambda_handler(event, context):

    # Get the object from the event
    source_bucket = event['Records'][0]['s3']['bucket']['name']
    key = urllib.unquote_plus(event['Records'][0]['s3']['object']['key'].encode('utf8'))
    try:
        #Reading the content of incoming file
        print("Extracting voicemail text from input voicemail transcript file")
        incoming_vm_file_name = s3.get_object(Bucket=source_bucket, Key=key)
        incoming_vm_timestamp = key.split('.')[0]
        incoming_vm_text = incoming_vm_file_name['Body'].read()
        

        #SENTIMENT DETECTION
        
        #Applying AWS Comprehend NLP sentiment detection capabilities on the incoming VM text
        print("Performing AWS Comprehend NLP sentiment detection on voicemail text")
        sentiment_response = comprehend.detect_sentiment(Text=incoming_vm_text, LanguageCode='en')                
        vm_sentiment = sentiment_response['Sentiment']

        #DOMINANT LANGUAGE DETECTION
        
        #Applying AWS Comprehend NLP language detection capabilities on the incoming VM text
        print("Performing AWS Comprehend NLP dominant language detection on voicemail text to identify English, Spanish or Other")
        lang_response = comprehend.detect_dominant_language(Text=incoming_vm_text) 
        vm_languages = lang_response['Languages']
        
        #Right now this code identifies only English and Spanish
        #Amazon Comprehend supports other languages too, but this code marks all other languages as 'other'
        for language in vm_languages:            
            lang_code = language['LanguageCode']
        
        if lang_code in ('en'):
            comprehend_detected_dom_lang = 'ENGLISH'
            
        if lang_code in ('es'):
            comprehend_detected_dom_lang = 'SPANISH'
        
        if lang_code not in ('es','en'):
            comprehend_detected_dom_lang = 'Other'
            
        
        #ENTITY DETECTION
        
        #Applying AWS Comprehend NLP entity detection capabilities on the incoming VM text   
        #Amazon Comprehend detects multiple entity types - person, location, date etc
        #In this code, we are identifying only person entity from the voicemail
        print("Performing AWS Comprehend NLP entity detection on voicemail text")
        detected_entities_response = comprehend.detect_entities(Text=incoming_vm_text, LanguageCode='en')
        detected_entities = detected_entities_response["Entities"]
        
        
        vm_person_name = 'Not available' #Initializing person entity name;default is not available
        
        for detected_entity in detected_entities:
            entity_type = detected_entity["Type"]    
            entity_text = detected_entity["Text"]
            
            if entity_type == 'PERSON': #Identifying name of individuals mentioned in the voicemail text if any
                vm_person_name = entity_text
                
         
        #Applying AWS Comprehend NLP detect key phrase capabilities on the incoming VM text
        phrases_response = comprehend.detect_key_phrases(Text=incoming_vm_text, LanguageCode='en')
        
          
        #NOTIFICATION
        
        #Identifying key domain specific terms related to each department. 
        #Used in deciding which department should be notified
        #Data used for department identification is stored in S3 bucket named - vmtrainbucket
        

        #function to return the defined entities to be matched for each department, from the S3 bucket
        def get_dept_entity_list(def_ent_file_name):
            train_data_bucket = "vmtrainbucket"
            this_entities_file_key = def_ent_file_name
            this_entities_file_name = s3.get_object(Bucket=train_data_bucket, Key=this_entities_file_key)
            defined_this_entities = this_entities_file_name['Body'].read()
            defined_this_entities_list = defined_this_entities.split(",")
            return(tuple(defined_this_entities_list))     
            
        #calling get department entity list function for Benefits Department
        ben_entities_file_key = "BenefitDept.csv"
        mem_str = get_dept_entity_list(ben_entities_file_key)
        
        #calling get department entity list function for Provider Department
        prov_entities_file_key = "ProviderDept.csv"
        prov_str = get_dept_entity_list(prov_entities_file_key)

        #calling get department entity list function for Claims Department        
        claim_entities_file_key = "ClaimsDept.csv"
        claim_str = get_dept_entity_list(claim_entities_file_key)

        #calling get department entity list function for Health Insurance Exchange Department
        #Assuming the Health Insurer operates in California,, defined entities related to HIX in California- called Covered California
        #HIX.csv in the vmtrainbucket S3 bucket can be changed to incorporate HIX entities for any Satate
        hix_entities_file_key = "HIX.csv"
        hix_str = get_dept_entity_list(hix_entities_file_key)

        #calling get department entity list function for Pharmacy Department        
        phar_entities_file_key = "PharmacyDept.csv"
        phar_str = get_dept_entity_list(phar_entities_file_key)


        #Initializing counters
        mem_count = 0
        prov_count = 0
        claim_count = 0
        hix_count = 0
        phar_count = 0
        
        
        '''
        1. Identifying key phrases
        #2. categorizing them with respect to department terms
        #3. incrementing associated counters'''
        key_phrases = phrases_response['KeyPhrases']
        print("Identifying Department to be notified ")
        for detected_phrase in key_phrases:
            
            phrase_text = detected_phrase["Text"]
            phrase_score = detected_phrase["Score"]
            
            if any(x in phrase_text.lower() for x in mem_str):
                mem_count = mem_count+1

            if any(x in phrase_text.lower() for x in prov_str):
                prov_count = prov_count+1
                
            if any(x in phrase_text.lower() for x in claim_str):
                claim_count = claim_count+1
                
            if any(x in phrase_text.lower() for x in hix_str):
                hix_count = hix_count+1
                
            if any(x in phrase_text.lower() for x in phar_str):
                phar_count = phar_count+1

        #Identifying which department should be notified
        dept_wrd_counts = {'mem_count':mem_count, 'prov_count':prov_count, 'claim_count':claim_count, 'phar_count':phar_count,'hix_count':hix_count}
        max_dept_wrd_counts = max(dept_wrd_counts, key=dept_wrd_counts.get)
        

        #Fetching sender email id from the S3 bucket where it is maintained
        #Sender email id to be used should be pre-registered with Amazon SES Service
        email_id_store_bucket = "vmdeptemailidbucket"
        this_sender_file_key = "Sender.txt"
        this_sender_file_name = s3.get_object(Bucket=email_id_store_bucket, Key=this_sender_file_key)
        defined_sender_email_id = this_sender_file_name['Body'].read()

        #Function to fetch recipient email id from the S3 bucket where it is maintained
        def get_dept_entity_list(recp_dept_email_file):
            email_id_store_bucket = "vmdeptemailidbucket"
            this_recp_file_key = recp_dept_email_file
            this_recp_file_name = s3.get_object(Bucket=email_id_store_bucket, Key=this_recp_file_key)
            defined_recp_email_id = this_recp_file_name['Body'].read()
            return(defined_recp_email_id)   
            
        #Function to fetch recipient email id from the S3 bucket where it is maintained
        #All recipient email ids/DLs to be used for individual departments should be pre-registered with Amazon SES Service        

            
        if max_dept_wrd_counts =='mem_count':
            print ('Department to be notified: Benefits department')
            print ('Sending email notification to Benefits department')
            SENDER = defined_sender_email_id
            RECIPIENT = get_dept_entity_list("BenefitDeptEmailDL.txt")


        if max_dept_wrd_counts =='prov_count':
            print ('Department to be notified: Provider department')
            print ('Sending email notification to Provider department')
            SENDER = defined_sender_email_id
            RECIPIENT = get_dept_entity_list("ProvDeptEmailDL.txt")


        if max_dept_wrd_counts =='claim_count':
            print ('Department to be notified: Claims department')
            print ('Sending email notification to Claims department')
            SENDER = defined_sender_email_id
            RECIPIENT = get_dept_entity_list("ClaimsDeptEmailDL.txt")


        if max_dept_wrd_counts =='hix_count':
            print ('Department to be notified: HIX department')
            print ('Sending email notification to HIX department')
            SENDER = defined_sender_email_id
            RECIPIENT = get_dept_entity_list("HIXDeptEmailDL.txt")

            
        if max_dept_wrd_counts =='phar_count':
            print ('Department to be notified: Pharmacy department')
            print ('Sending email notification to Pharmacy department')
            SENDER = defined_sender_email_id
            RECIPIENT = get_dept_entity_list("PharmacyDeptEmailDL.txt")


            
        #Sending notification email to respective department
        # The subject line for the email.
        SUBJECT = "New Voicemail ALERT: [Received "+incoming_vm_timestamp+ " PST; About - " +vm_person_name.upper()+ "; Language - " +comprehend_detected_dom_lang+"; Sentiment - " +vm_sentiment+ "]"

        # The email body for recipients with non-HTML email clients.
        BODY_TEXT1 = "Received this voicemail related to your department.  Please take necessary action"
        BODY_TEXT2 = "  ----->>>>>>>>>>>>>>>>> VOICEMAIL TEXT IS : "
        BODY_TEXT3 = incoming_vm_text
        BODY_TEXT4 = "<<<<<<<<<<<<<<<<<<----- "

        # The character encoding for the email.
        CHARSET = "UTF-8"

        # Create a new SES resource and specify a region.
        client = boto3.client('ses',region_name=AWS_REGION)
               
        # Try to send the email.
        try:
            #Provide the contents of the email.
            response = client.send_email(
                Destination={
                    'ToAddresses': [
                        RECIPIENT,
                    ],
                },
                Message={
                    'Body': {
                        'Html': {
                            'Charset': CHARSET,
                            'Data': BODY_TEXT1+BODY_TEXT2+"'"+BODY_TEXT3+"'"+BODY_TEXT4,
                        },
                        'Text': {
                            'Charset': CHARSET,
                            'Data': '',
                        },
                    },
                    'Subject': {
                        'Charset': CHARSET,
                        'Data': SUBJECT,
                    },
                },
                Source=SENDER,

            )
        # Display an error if something goes wrong.	
        except ClientError as e:
            print(e.response['Error']['Message'])
        else:
            print("Email sent! Message ID is:"),
            print(response['MessageId'])
                        
    
        #ARCHIVING
        
        #Copying the incoming voicemail file to archive location post processing
       
        print ('Archiving input voicemail file')
        target_bucket = 'vmarchivebucket' # bucket where processed voicemail files will be archived
        copy_source = {'Bucket':source_bucket, 'Key':key}
        waiter = s3.get_waiter('object_exists')
        waiter.wait(Bucket=source_bucket, Key=key)
        s3.copy_object(Bucket=target_bucket, Key=key, CopySource=copy_source)
        
        #Deleting the incoming file post processing and archival
        s3.delete_object(Bucket=source_bucket, Key=key)
        print('Completed NLP and Email Notification for {} from bucket {}. '.format(key, source_bucket))    
        return "OK"
        
    except Exception as e:
        print(e)
        print('Error while doing NLP on {} from bucket {}. '.format(key, source_bucket))
        raise e
        
        

