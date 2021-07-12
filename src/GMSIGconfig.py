''' GMSIG.py
Configuration file for common parameters in the GMSIG ('Get Meraki Settings Into Git') project
'''

# Preference is to define MERAKI_API_KEY at executing user's environment, but it can be set here also (less secure)
api_key = ''

get_operation_mappings_file = 'API_GET_operations.csv'
meraki_base_api_url = 'https://api.meraki.com/api/v1/'
meraki_base_path = '/opt/MerakiGit/orgid'
log_path = 'logs'  # Using a subordinate directory from location of Python script called 'logs' - change to suite

git_base_path = '/opt/MerakiGit/orgid'
git_user_email = 'somebody@example.com'
git_user_name = 'FirstName LastName'

web_publishing_dir = '/var/www/html/DevNetDashboards/MerakiGit'
web_url = '/DevNetDashboards/MerakiGit'

max_threads = 3
max_retries = 4
backup_format = 'json'