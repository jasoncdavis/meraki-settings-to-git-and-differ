"""Get Meraki Settings Into Git (GetMerakiSettingsIntoGit.py)

#                                                                      #
Fetches all the network identifiers (NetworkIds) from an identified 
Meraki organization (orgid); creates networkid directories in a git
repo, then populates with network-specific device directories.
Network and devivce-centric settings are populated as JSON documents
in the git repo.

Required inputs/variables can be defined in the GMSIGconfig.py file
    API key - see below
    git_repo_path - git repository directory path on local server

Either input your API key below by uncommenting the 'API_KEY =' line 
or set an environment variable (preferred) to define your API key.
The former is insecure and not recommended.
For example, in Linux/macOS:
   $ export MERAKI_DASHBOARD_API_KEY=09....73

Outputs:
    JSON files of Meraki org/network/device settings into the
git_repo_path location

Version log
v2      2021-0324   Enhancing with asyncio functionality to accomodate 
larger environments
v3      2021-0421   Refactor to work with single customer/orgid for 
DevNet Automation Exchange
v4      2021-0514   Refactor, increased doco in preparation for
DevNet Automation Exchange publishing

Credits:
EXTREME amounts of credit goes to Maria Papazoglou (GitHub @mpapazog)
formerly of the Cisco Meraki Dev team who provided a significant
component of this work from her repo at:
https://github.com/meraki/automation-scripts/tree/master/backup_configs

I had written a similar solution, also including asyncio functionality,
but she had a more elegant approach that also included OpenAPI parsing,
so I forked her work and added the github archiving function.
Thank you Maria!
"""
__version__ = '4'
__author__ = 'Jason Davis - jadavis@cisco.com'
__license__ = "Cisco Sample Code License, Version 1.1 - https://developer.cisco.com/site/license/cisco-sample-code-license/"

import argparse
import csv
from datetime import datetime
import os
import sys
import json
import yaml
import git
from datetime import datetime
import glob
import shutil
import asyncio

import meraki.aio
import re
import subprocess
import math
import requests

from meraki.config import API_KEY_ENVIRONMENT_VARIABLE, OUTPUT_LOG
import GMSIGconfig as env


# Module variables
# Configure API_KEY if setting inside Python script, otherwise set environment variable as describes in readme above
# eg 40 character API_KEY = '1234567890abcdef1234567890abcdef12345678'
API_KEY = ''

log_path = "logs"  # Using a subordinate directory from location of Python script called 'logs' - change to suite

git_user_email = env.git_user_email
git_user_name = env.git_user_name

# Global variables for script - do not change
ORG_ID = None
TOTAL_CALLS = 0
COMPLETED_OPERATIONS = set()
DEFAULT_CONFIGS = []
DEVICES = NETWORKS = TEMPLATES = []

########################################
####### Module Function definitions

async def archive_appliance_vlans(dashboard, networks):
    """Archive settings for appliances VLANs & VLAN ports, or single LAN 
    network
    
    Processes through networks list where productTypes = 'appliance',
    creates file paths and JSON files, creates the API call structure and
    sends to make_calls function

    :param dashboard: Meraki Dashboard API session
    :param networks: list of networks to be processed
    :returns: None
    """
    calls = []

    appliance_networks = [n for n in networks if 'appliance' in n['productTypes']]
    for network in appliance_networks:
        net_name = network['name']
        net_id = network['id']

        file_path = f'networks/{net_id} - {net_name}'

        # VLANs enabled, as presence of the vlans_settings file indicates non-default configuration
        if os.path.exists(f'{file_path}/network_ApplianceVlansSettings.json'):
            operations = ['getNetworkApplianceVlans', 'getNetworkAppliancePorts']
        else:
            operations = ['getNetworkApplianceSingleLan']

        # Make possibly multiple API calls
        scope = 'appliance'
        for operation in operations:
            file_name = generate_file_name(operation)
            function_call = f'dashboard.{scope}.{operation}(net_id)'

            calls.append(
                {
                    'operation': operation,
                    'function_call': function_call,
                    'file_name': file_name,
                    'file_path': file_path,
                    'net_id': net_id,
                }
            )

    await make_calls(dashboard, calls)


async def archive_ble_settings(dashboard, networks, devices):
    """Archive settings for Bluetooth device settings for networks using 
    unique BLE advertising
    
    Processes through networks and devices list where productTypes = 
    'wireless', creates file paths and JSON files, creates the API call 
    structure and sends to make_calls function

    :param dashboard: Meraki Dashboard API session
    :param networks: list of networks to be processed
    :param devices: list of devices to be processed
    :returns: None
    """
    
    calls = []

    wireless_networks = [n for n in networks if 'wireless' in n['productTypes']]
    for network in wireless_networks:
        # Filter for those networks using unique BLE advertising
        net_name = network['name']
        net_id = network['id']

        file_path = f'networks/{net_id} - {net_name}'

        if os.path.exists(f'{file_path}/network_WirelessBluetoothSettings.json'):
            with open(f'{file_path}/network_WirelessBluetoothSettings.json') as fp:
                config = json.load(fp)
            if config['advertisingEnabled'] and config['majorMinorAssignmentMode'] == 'Unique':
                for d in devices:
                    if d['networkId'] == net_id and device_type(d['model']) == 'wireless':
                        serial = d['serial']
                        operation = 'getDeviceWirelessBluetoothSettings'
                        file_name = f'{generate_file_name(operation)}_{serial}'
                        tags = ['wireless', 'configure', 'bluetooth', 'settings']
                        scope = generate_scope(tags)
                        function_call = f'dashboard.{scope}.{operation}(serial)'

                        calls.append(
                            {
                                'operation': operation,
                                'function_call': function_call,
                                'file_name': file_name,
                                'file_path': file_path,
                                'serial': serial,
                            }
                        )

    await make_calls(dashboard, calls)


async def archive_devices(dashboard, endpoints, devices):
    """Archive settings for devices
    
    Processes through devices list and API endpoint list, filtering out
    'skipped' items from the GET_API.CSV file - creates the API call 
    structure and sends to make_calls function

    :param dashboard: Meraki Dashboard API session
    :param endpoints: list of API endpoint calls to be processed
    :param devices: list of devices to be processed
    :returns: None
    """
    os.mkdir('devices')
    calls = []

    for device in devices:
        serial = device['serial']
        model = device['model']
        family = device_type(model)
        file_path = f'devices/{serial} - {model}'
        os.mkdir(file_path)

        for ep in endpoints:
            logic = ep['Logic']
            operation = ep['operationId']
            file_name = generate_file_name(operation)
            tags = eval(ep['tags'])
            scope = generate_scope(tags)
            function_call = f'dashboard.{scope}.{operation}(serial)'

            if operation.startswith('getDevice') and logic not in ('skipped', 'script') and \
                    ((scope == 'devices' and family in ('wireless', 'switch', 'appliance')) or (scope == family)):
                calls.append(
                    {
                        'operation': operation,
                        'function_call': function_call,
                        'file_name': file_name,
                        'file_path': file_path,
                        'serial': serial,
                    }
                )

    await make_calls(dashboard, calls)


async def archive_mr_ssids(dashboard, endpoints, networks):
    """Archive settings for SSID-specific settings
    
    Processes through networks list and API endpoint list, filtering for
    'wireless' productTypes endpoints from the GET_API.CSV file -
    creates the API call  structure and sends to make_calls function

    :param dashboard: Meraki Dashboard API session
    :param endpoints: list of API endpoint calls to be processed
    :param networks: list of networks to be processed
    :returns: None
    """
    calls = []

    wireless_networks = [n for n in networks if 'wireless' in n['productTypes']]
    for network in wireless_networks:
        template = True if 'tags' not in network else False
        bound = True if 'configTemplateId' in network else False

        # Filter for those SSIDs that are configured (without the string "Unconfigured" in the name)
        net_name = network['name']
        net_id = network['id']

        file_path = f'networks/{net_id} - {net_name}'

        with open(f'{file_path}/network_WirelessSsids.json') as fp:
            config = json.load(fp)
        config_ssids = ['Unconfigured' not in ssid['name'] for ssid in config]
        for num in range(0, 15):
            if config_ssids[num]:
                for ep in endpoints:
                    logic = ep['Logic']
                    operation = ep['operationId']
                    file_name = f'{generate_file_name(operation)}_ssid_{num}'
                    tags = eval(ep['tags'])
                    scope = generate_scope(tags)
                    function_call = f'dashboard.{scope}.{operation}(net_id, {num})'

                    if logic == 'ssids' and tags:
                        process_call = True
                        if process_call:
                            calls.append(
                                {
                                    'operation': operation,
                                    'function_call': function_call,
                                    'file_name': file_name,
                                    'file_path': file_path,
                                    'net_id': net_id,
                                }
                            )

    await make_calls(dashboard, calls)


async def archive_ms_profiles(dashboard, templates):
    """Archive settings for configuration templates' switch profiles
    
    Processes through templates list, filtering for 'switch' productTypes 
    endpoints from the GET_API.CSV file -
    creates the API call  structure and sends to make_calls function

    :param dashboard: Meraki Dashboard API session
    :param templates: list of meraki settings templates to be processed
    :returns: None
    """
    calls = []

    switch_templates = [t for t in templates if 'switch' in t['productTypes']]
    for template in switch_templates:
        template_name = template['name']
        net_id = template['id']

        file_path = f'networks/{template_name} - {net_id}'

        operation = 'getOrganizationConfigTemplateSwitchProfiles'
        file_name = f'{generate_file_name(operation)}'
        tags = ['switch', 'configure', 'configTemplates', 'profiles']
        scope = generate_scope(tags)
        function_call = f'dashboard.{scope}.{operation}(ORG_ID, net_id)'

        calls.append(
            {
                'operation': operation,
                'function_call': function_call,
                'file_name': file_name,
                'file_path': file_path,
                'net_id': net_id,
            }
        )

    await make_calls(dashboard, calls)


async def archive_ms_profile_ports(dashboard, templates):
    """Archive settings for configuration templates' switch profiles' ports
    
    Processes through templates list, filtering for 'switch' productTypes 
    endpoints from the GET_API.CSV file.
    Where profile templates exist, process profile port items.
    Creates the API call structure and sends to make_calls function

    :param dashboard: Meraki Dashboard API session
    :param templates: list of meraki settings templates to be processed
    :returns: None
    """
    calls = []

    switch_templates = [t for t in templates if 'switch' in t['productTypes']]
    for template in switch_templates:
        template_name = template['name']
        net_id = template['id']

        file_path = f'networks/{template_name} - {net_id}'

        if os.path.exists(f'{file_path}/org_ConfigTemplateSwitchProfiles.json'):
            with open(f'{file_path}/org_ConfigTemplateSwitchProfiles.json') as fp:
                config = json.load(fp)

            for profile in config:
                profile_id = profile['switchProfileId']
                operation = 'getOrganizationConfigTemplateSwitchProfilePorts'
                file_name = f'{generate_file_name(operation)}_{profile_id}'
                tags = ['switch', 'configure', 'configTemplates', 'profiles', 'ports']
                scope = generate_scope(tags)
                function_call = f'dashboard.{scope}.{operation}(ORG_ID, net_id, profile_id)'

                calls.append(
                    {
                        'operation': operation,
                        'function_call': function_call,
                        'file_name': file_name,
                        'file_path': file_path,
                        'net_id': net_id,
                        'profile_id': profile_id,
                    }
                )

    await make_calls(dashboard, calls)


async def archive_networks(dashboard, endpoints, networks):
    """Archive settings for networks and templates
    
    Processes through networks and templates lists, filters API calls/
    endpoints from the GET_API.CSV file that should be 'skipped'.
    Processes 'network-level' API endpoints, creating their JSON setting
    representation in a 'network' subfolder.
    Creates the API call structure and sends to make_calls function

    :param dashboard: Meraki Dashboard API session
    :param endpoint: list of Meraki APIs to be processed
    :param networks: list of Meraki networks to be processed
    :returns: None
    """
    os.mkdir('networks')
    calls = []

    for network in networks:
        net_name = network['name']
        net_id = network['id']
        products = network['productTypes']
        template = True if 'tags' not in network else False
        bound = True if 'configTemplateId' in network else False
        file_path = f'networks/{net_id} - {net_name}'
        os.mkdir(file_path)

        for ep in endpoints:
            logic = ep['Logic']
            operation = ep['operationId']
            file_name = generate_file_name(operation)
            tags = eval(ep['tags'])
            scope = generate_scope(tags)
            function_call = f'dashboard.{scope}.{operation}(net_id)'

            # API calls that apply to networks, or the majority of settings that also work for templates
            if operation.startswith('getNetwork') and logic not in ('skipped', 'script', 'ssids'):
                # Check whether endpoint applies to the network based on its component products
                proceed = False
                if scope == 'networks':
                    if logic not in ('', 'non-template', 'non-bound'):
                        if set(logic.split(',')).intersection(products):
                            proceed = True
                    else:
                        proceed = True
                elif scope in products:
                    proceed = True

                # Check for template/bound logic
                if proceed:
                    if (not template and not bound) or (bound and logic != 'non-bound') or \
                            (template and logic != 'non-template'):
                        calls.append(
                            {
                                'operation': operation,
                                'function_call': function_call,
                                'file_name': file_name,
                                'file_path': file_path,
                                'net_id': net_id,
                            }
                        )

            # For getNetworkWirelessRfProfiles, which has an optional parameter includeTemplateProfiles
            elif operation == 'getNetworkWirelessRfProfiles' and 'wireless' in products:
                if bound:
                    function_call = function_call[:-1] + ', includeTemplateProfiles=True)'
                calls.append(
                    {
                        'operation': operation,
                        'function_call': function_call,
                        'file_name': file_name,
                        'file_path': file_path,
                        'net_id': net_id,
                    }
                )

    await make_calls(dashboard, calls)


async def archive_org(dashboard, endpoints):
    """Backup configuration for organization
    
    Processes through API calls/endpoints from the GET_API.CSV file and
    filters ones that should be 'skipped'.
    Processes 'org-level' API endpoints, creating their JSON setting
    representation in a top-level folder by org_id.
    Creates the API call structure and sends to make_calls function

    :param dashboard: Meraki Dashboard API session
    :param endpoint: list of Meraki APIs to be processed
    :returns: None
    """
    calls = []
    
    for ep in endpoints:
        logic = ep['Logic']
        operation = ep['operationId']
        file_name = generate_file_name(operation)
        tags = eval(ep['tags'])
        scope = generate_scope(tags)
        function_call = f'dashboard.{scope}.{operation}(ORG_ID)'
        
        if operation.startswith('getOrganization') and logic not in ('skipped', 'script'):
            # Iterate through all pages for paginated endpoints
            params = [p['name'] for p in eval(ep['parameters'])]
            if 'perPage' in params:
                function_call = function_call[:-1] + ", total_pages='all')"
    
            calls.append(
                {
                    'operation': operation,
                    'function_call': function_call,
                    'file_name': file_name,
                    'file_path': '',
                }
            )
    await make_calls(dashboard, calls)


async def async_call(dashboard, call):
    """Asynchronous function to make a REST API call
    
    Enables asynchronous processing of REST API calls.  Takes in the API
    call from parent function, extracts some parameters to handle type,
    desired filename and path, and sets tags related to serial number,
    net ids, and profiles (if applicable)

    :param dashboard: Meraki Dashboard API session
    :param call: Meraki API call to be processed
    :returns: Either results of API call or None
    """
    global TOTAL_CALLS
    TOTAL_CALLS += 1
    
    operation = call['operation']
    function_call = call['function_call']
    file_name = call['file_name']
    file_path = call['file_path']
    
    serial = net_id = profile_id = identifier = None
    if 'serial' in call:
        serial = call['serial']
        identifier = serial
    if 'net_id' in call:
        net_id = call['net_id']
        identifier = net_id
    if 'profile_id' in call:
        profile_id = call['profile_id']
        identifier = profile_id

    try:
        response = await eval(function_call)
    except meraki.AsyncAPIError as e:
        print(f'Error with {identifier}: {e}')
        return None
    else:
        return {
            'operation': operation,
            'response': response,
            'file_name': file_name,
            'file_path': file_path,
            'net_id': net_id,
            'serial': serial,
            'profile_id': profile_id,
		}


def commit_processed_files(org_id):
    """Performs git commit on files that were newly created in the tracked
    repo directory.
    
    Helper function that performs a git commit on all the newly created
    settings JSON files.  Creates log of scan record.

    :param org_id: Meraki organization id for customer instance
    :returns: Either results of API call or None
    """

    now = datetime.now()
    scanfinish_datetime = now.strftime("%Y-%m-%d--%H-%M")
    date_time_verbose = now.strftime("%A, %B %d, %Y at %H:%M:%S %Z")

    git_repo_path = f'{env.git_base_path}/{org_id}/settings'
    # Add all files to repo and commit
    repo = git.Repo(git_repo_path)
    repo.git.add(git_repo_path)
    try:
        repo.git.commit('-m',f"'Commit from Meraki scan finished on {date_time_verbose}'")
    except git.exc.GitCommandError as e:
        print(f'Git commit returned error {e.stdout}')
    print(f'Repo description: {repo.description}')
    print(f'Repo active branch is {repo.active_branch}')
    print(f'Repo status is {repo.git.status()}')


    scanrecord = f"""{{
"scanend": "{scanfinish_datetime}",
"orgid": "{org_id}"
}}"""

    scaninfo_dir = f'{env.meraki_base_path}/{org_id}/scaninfo'
    if not os.path.exists(scaninfo_dir):
        os.makedirs(scaninfo_dir)

    with open(f'{scaninfo_dir}/scanlog-{scanfinish_datetime}.json', "w") as outputfile:
                outputfile.write(scanrecord + '\n')
                print(f'  Wrote scan log to file: {scaninfo_dir}/scanlog-{scanfinish_datetime}.json')
            

async def main_async(api_key, operations, endpoints, tag):
    """Main function that queues all Meraki scan categories (org, networks,
    devices, vlans, and other specially handled use cases).
    
    Initiates the Meraki AsyncIO (meraki.aio) session and calls all polled
    categories.  Tracks and checks any unused API calls from OpenAPISpec
    comparison.  [This allows us to extend and refine the API calls we
    want to process or 'skip']

    :param api_key: Meraki user's API Key
    :param operations: list of API endpoints from OpenAPISpec
    :param endpoints: list of API endpoints to be processed from CSV input
    :param tag: optional list of Meraki tags to filter work
    :returns: None
    """
    global DEVICES, NETWORKS, TEMPLATES
    async with meraki.aio.AsyncDashboardAPI(
        api_key, 
        maximum_concurrent_requests=env.max_threads, 
        maximum_retries=env.max_retries, 
        print_console=True, 
        suppress_logging=False,
        output_log=True,
        log_file_prefix=os.path.basename(__file__)[:-3],
        log_path='../scaninfo'
        ) as dashboard:
        # Backup org
        await archive_org(dashboard, endpoints)

        # Filter on networks/devices, if optional tag provided by user
        if tag:
            TEMPLATES = []
            NETWORKS = [n for n in NETWORKS if tag in n['tags']]
            DEVICES = [d for d in DEVICES if d['networkId'] in [n['id'] for n in NETWORKS]]

        # Backup devices
        await archive_devices(dashboard, endpoints, DEVICES)
        
        # Backup networks and configuration templates
        await archive_networks(dashboard, endpoints, NETWORKS + TEMPLATES)

        # Backup either VLANs or single-LAN addressing for appliances
        await archive_appliance_vlans(dashboard, NETWORKS + TEMPLATES)

        # Backup switch profiles for configuration templates
        await archive_ms_profiles(dashboard, TEMPLATES)

        #Backup switch profiles' ports for configuration templates
        await archive_ms_profile_ports(dashboard, TEMPLATES)

        # Backup SSID-specific settings for configured SSIDs
        await archive_mr_ssids(dashboard, endpoints, NETWORKS + TEMPLATES)

        # Backup Bluetooth device settings for networks using unique BLE advertising
        await archive_ble_settings(dashboard, NETWORKS, DEVICES)

    # Check any operations that were not used
    for ep in endpoints:
        if ep['Logic'] == 'skipped':
            operation = ep['operationId']
            COMPLETED_OPERATIONS.add(operation)
    unfinished = [op for op in operations if op['operationId'] not in COMPLETED_OPERATIONS]
    if unfinished:
        print(f'\n###DONE\nCheck {env.git_base_path}/{ORG_ID}/scaninfo/API_GET_operations.csv and consider updating.\nPut new entries as \'skipped\' to ignore in future scans.\n{len(unfinished)} API endpoints found in latest OpenAPI spec that were not called during this backup process:')
        for op in unfinished:
            print(op['operationId'])


async def make_calls(dashboard, calls):
    """Make multiple API calls asynchronously
    
    Builds task list of all API calls, then sends to async_call function.
    Awaits results and as completed processes the results, sending the
    follow-on work to save_data function to create JSON record.

    :param dashboard: Meraki Dashboard API session
    :param calls: list of API endpoints to be processed
    :returns: None
    """
    global COMPLETED_OPERATIONS, DEVICES, NETWORKS, TEMPLATES

    tasks = [async_call(dashboard, call) for call in calls]
    for task in asyncio.as_completed(tasks):
        results = await task
        if results:
            operation = results['operation']
            response = results['response']
            file_name = results['file_name']
            file_path = results['file_path']
            
            save_data(file_name, response, file_path)
            
            # Update global variables
            COMPLETED_OPERATIONS.add(operation)
            if operation == 'getOrganizationNetworks':
                NETWORKS = response
            elif operation == 'getOrganizationConfigTemplates':
                TEMPLATES = response
            elif operation == 'getOrganizationDevices':
                DEVICES = response


def archive_settings(api_key, org_id, filter_tag):
    """Main function to coordinate all archive settings functions
    
    Builds task list of all API calls, then sends to async_call function.
    Awaits results and as completed processes the results, sending the
    follow-on work to save_data function to create JSON record.
    
    :param api_key: Meraki Dashboard API key of authorized user
    :param org_id: Meraki customer organization id
    :param filter_tag: list of Meraki tags used to filter work
    :returns: time_ran string reflecting processing time and TOTAL_CALLS
        integer reflecting total API call count
    """
    global GET_OPERATION_MAPPINGS_FILE, DEFAULT_CONFIGS_DIRECTORY, DEFAULT_CONFIGS, ORG_ID, TOTAL_CALLS

    # Calculate total time
    start = datetime.now()
    auth_header = { 'X-Cisco-Meraki-API-Key': api_key }
    
    # Get operations from current dashboard OpenAPI specification
    openapispec = requests.get(f'{env.meraki_base_api_url}/openapiSpec', headers=auth_header).json()
    current_operations = []

    # Extract GET methods from OpenAPI spec
    for uri in openapispec['paths']:
        methods = openapispec['paths'][uri]
        # for method in methods:
        #     current_operations.append(spec['paths'][uri][method])
        #if 'get' in methods and ('post' in methods or 'put' in methods):
        #	current_operations.append(openapispec['paths'][uri]['get'])
        if 'get' in methods:
            current_operations.append(openapispec['paths'][uri]['get'])

    # Export current GET operations to spreadsheet; for comparison later to check for new operations that were not used
    output_file = open(f'{env.git_base_path}/{str(org_id)}/scaninfo/latest-openapi_GET_operations.csv', mode='w', newline='\n')
    field_names = ['operationId', 'tags', 'description', 'parameters']
    csv_writer = csv.DictWriter(output_file, field_names, quoting=csv.QUOTE_ALL, extrasaction='ignore')
    csv_writer.writeheader()
    for op in current_operations:
        csv_writer.writerow(op)
    output_file.close()

    # Read input mappings of archive GET operations, the actual list of API calls that will be made
    input_mappings = []

    try:
        with open(f'{env.git_base_path}/{str(org_id)}/scaninfo/{env.get_operation_mappings_file}', encoding='utf-8-sig') as fp:
            csv_reader = csv.DictReader(fp)
            for row in csv_reader:
                input_mappings.append(row)
    except IOError as ex:
        shutil.copyfile('default_API_GET_operations.csv', f'{env.git_base_path}/{str(org_id)}/scaninfo/{env.get_operation_mappings_file}')

        print(f'Possible first run with {org_id} - Copied and using default scan parameters file\n\tupdate {env.git_base_path}/{str(org_id)}/scaninfo/{env.get_operation_mappings_file} to suite needs for future scans, if desired.')
        with open(f'{env.git_base_path}/{str(org_id)}/scaninfo/{env.get_operation_mappings_file}', encoding='utf-8-sig') as fp:
            csv_reader = csv.DictReader(fp)
            for row in csv_reader:
                input_mappings.append(row)

    # Reset git directory
    os.chdir(f'{env.git_base_path}/{org_id}/settings')
    time_now = datetime.now()
    files = glob.glob(f'{env.git_base_path}/{org_id}/settings/*')

    # Remove 'special' files from list that we'd rather retain; retain_files should be comma-separated set
    retain_files = {f'{env.git_base_path}/{org_id}/settings/repo_init'}
  
    files = [elem for elem in files if elem not in retain_files]
    for file in files:
        try:
            os.remove(file)
        except IsADirectoryError:
            shutil.rmtree(file)
        except OSError as e:
            print("Error: %s : %s" % (file, e.strerror))

    # Run archive process
    ORG_ID = org_id
    asyncio.run(main_async(api_key, current_operations, input_mappings, filter_tag))

    # Calculate total time
    end = datetime.now()
    time_ran = end - start
    return time_ran, TOTAL_CALLS


def check_git_status(orgid, orgname):
    """Checks status of git repo and creates repo if needed
    
    Checks status of git repo and creates repo if needed.  Sets repo
    description and creates placeholder init file for date creation
    reference.  Performs initial commit of repo.

    :param orgid: Meraki customer organization id
    :param orgname: Meraki customer organization name
    :returns: None
    """
    try:
        my_repo = git.Repo(f'{env.git_base_path}/{orgid}/settings')
    except git.exc.InvalidGitRepositoryError:
        print(f'Could not find existing git repository at {env.git_base_path}/{orgid}/settings')
        mrepo = git.Repo.init(f'{env.git_base_path}/{orgid}/settings')
        mrepo.description = f'Meraki settings git repo for {orgname} with orgid {orgid}'
        print(f'Created git repository at {env.git_base_path}/{orgid}/settings/.git')
        open(f'{env.git_base_path}/{orgid}/settings/repo_init', 'w').close()
        mrepo.index.add(f'{env.git_base_path}/{orgid}/settings/repo_init')
        mrepo.index.commit("Initial commit")
        my_repo = git.Repo(f'{env.git_base_path}/{orgid}/settings')
    print(f'Repo description: {my_repo.description}')
    print(f'Repo active branch is {my_repo.active_branch}')


def check_orgdir_status(orgid):
    """Check status of org existance and directory structure in git repo

    Check for existance of Meraki customer's org_id in the git repo.
    Creates directory structure, if missing.

    :param orgid: Meraki customer organization id
    :returns: None
    """
    if not os.path.exists(f'{env.git_base_path}/{orgid}/settings'):
        try: 
            os.makedirs(f'{env.git_base_path}/{orgid}/settings')
            print('Created initial org-specific Meraki base directory')
            print('Created initial org-specific Meraki settings directory')
        except PermissionError:
            print(f'Unable to create directory structure - Check permissions on {env.git_base_path}')
            sys.exit(1)
        except:
            print("Unexpected error:", sys.exc_info()[0])
            sys.exit(1)
    if not os.path.exists(f'{env.git_base_path}/{orgid}/scaninfo'):
        try: 
            os.makedirs(f'{env.git_base_path}/{orgid}/scaninfo')
            print('Created initial org-specific Meraki scaninfo directory')
        except PermissionError:
            print(f'Unable to create directory structure - Check permissions on {env.git_base_path}')
            sys.exit(1)
        except:
            print("Unexpected error:", sys.exc_info()[0])
            sys.exit(1)
    

def device_type(model):
    """Helper function that returns type of device based on model number
    
    Helper function that returns type of device based on model number.
    Used for logic look-ups in archive_devices().

    :param model: Meraki device model string
    :returns: string of device model/family in 'friendly' form or None if
        no match
    """
    family = model[:2]
    if family == 'MR':
        return 'wireless'
    elif family == 'MS':
        return 'switch'
    elif family == 'MV':
        return 'camera'
    elif family == 'MG':
        return 'cellularGateway'
    elif family in ('MX', 'vM', 'Z3', 'Z1'):
        return 'appliance'
    else:
        return None


def estimate_backup(api_key, org_id, filter_tag):
    """Estimates Meraki settings archive run-time.

    Provides CLI output showing the estimated time to do the Meraki 
    settings archive.  Uses some prior observation data to gauge the
    different device model results

    :param api_key: Meraki Dashboard REST API key for authorized user
    :param org_id: Meraki customer organization identifier
    :param filter_tag: list of Meraki tags used to filter work
    :returns: None, but output of time estimate is printed to CLI
    """
    print('Working, please be patient as we run calculations - may take a minute or so.', end='', flush=True)
    try:
        merakisession = meraki.DashboardAPI(api_key, suppress_logging=True)
    except meraki.APIError:
        sys.exit('Please check that you have both the correct API key and org ID set.')
    else:        
        networks = merakisession.organizations.getOrganizationNetworks(org_id, total_pages='all')
        print('.', end='', flush=True)
        templates = merakisession.organizations.getOrganizationConfigTemplates(org_id)
        print('.', end='', flush=True)
        devices = merakisession.organizations.getOrganizationDevices(org_id, total_pages='all')
        print('.', end='', flush=True)
        if filter_tag:
            networks = [n for n in networks if filter_tag in n['tags']]
            templates = []
            devices = [d for d in devices if d['networkId'] in [n['id'] for n in networks]]
        org_calls = 19

        # Estimate of API calls for devices
        total_devices = len(devices)
        mr_devices = len([d for d in devices if d['model'][:2] == 'MR'])
        print('.', end='', flush=True)
        ms_devices = len([d for d in devices if d['model'][:2] == 'MS'])
        print('.', end='', flush=True)
        mv_devices = len([d for d in devices if d['model'][:2] == 'MV'])
        print('.', end='', flush=True)
        mg_devices = len([d for d in devices if d['model'][:2] == 'MG'])
        print('.', end='', flush=True)
        mt_devices = len([d for d in devices if d['model'][:2] == 'MT'])
        print('.', end='', flush=True)
        mx_devices = total_devices - mr_devices - ms_devices - mv_devices - mg_devices - mt_devices
        device_calls = (mr_devices + ms_devices + mx_devices) + mr_devices + 2 * ms_devices + 3 * mv_devices + 2 * mg_devices

        # Estimate of API calls for networks
        mr_networks = len([n for n in networks if 'wireless' in n['productTypes']]) + \
            len([t for t in templates if 'wireless' in t['productTypes']])
        print('.', end='', flush=True)
        ms_networks = len([n for n in networks if 'switch' in n['productTypes']]) + \
            len([t for t in templates if 'switch' in t['productTypes']])
        print('.', end='', flush=True)
        mx_networks = len([n for n in networks if 'appliance' in n['productTypes']]) + \
            len([t for t in templates if 'appliance' in t['productTypes']])
        print('.', end='', flush=True)
        mg_networks = len([n for n in networks if 'cellularGateway' in n['productTypes']]) + \
            len([t for t in templates if 'cellularGateway' in t['productTypes']])
        print('.', end='', flush=True)
        mv_networks = len([n for n in networks if 'camera' in n['productTypes']])
        print('.')
        network_calls = 19 * mr_networks + 22 * ms_networks + 32 * mx_networks + 6 * mg_networks + 4 * mv_networks

        total_calls = org_calls + device_calls + network_calls
        minutes = math.ceil(total_calls / 4 / 60)

        hours = minutes // 60
        remainingmin = minutes % 60

        print(f'''Org {org_id} has {total_devices} total devices and {mr_networks + ms_networks + mx_networks + mv_networks} total networks
  MR: {mr_devices : >7} devices : {mr_networks : >8} networks
  MS: {ms_devices : >7} devices : {ms_networks : >8} networks
  MX: {mx_devices : >7} devices : {mx_networks : >8} networks
  MG: {mg_devices : >7} devices : {mg_networks : >8} networks
  MV: {mv_devices : >7} devices : {mv_networks : >8} networks
 ''')
        if minutes > 60:
            print(f'''Approximately {total_calls:,} API calls will be made, taking about {minutes} minutes or {hours}h {remainingmin}m.''')
        else:
            print(f'''Approximately {total_calls:,} API calls will be made, taking about {minutes} minutes.''')


def generate_file_name(operation):
    """Helper function to format the file name generated from the operation
        ID

    Helper function to format the file name used to store the settings
    derived from the operation.

    :param operation: string representing the operation type
    :returns: string of operation name
    """
    if operation == 'getOrganization':
        return('org_Organization')
    else:
        opname = operation.replace('getOrganization', 'org_').replace('getDevice', 'device_').replace('getNetwork', 'network_')
        return opname


def generate_scope(tags):
    """Helper function to format the scope, which is the middle part of the
     actual API function call

    Helper function to format the scope which defines org, network or
    device level perspective.

    :param tags: scope of query
    :returns: tag item
    """
    return tags[0]


def get_metrics(orgid):
    """Peek into archived git repo file directories and count settings, 
    networks and devices collected

    Counts org-level settings, device counts and device-level settings, 
    and network counts and network-level settings

    :param orgid: Meraki customer organization identifier
    :returns: values of org, network and device-level counts and settings
    """
    os.chdir(f'{env.meraki_base_path}/{orgid}/settings/')
    org_settings_count = int(subprocess.run("ls -l *.json | wc -l", shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True).stdout.rstrip())
    device_count = int(subprocess.run("ls -l devices/ | wc -l", shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True).stdout.rstrip()) - 1
    device_settings_count = int(subprocess.run("ls -l devices/*/*.json | wc -l", shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True).stdout.rstrip())
    network_count = int(subprocess.run("ls -l networks/ | wc -l", shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True).stdout.rstrip()) - 1
    network_settings_count = int(subprocess.run("ls -l networks/*/*.json | wc -l", shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True).stdout.rstrip())

    print(f'Org settings: {org_settings_count}')
    print(f'Device count: {device_count}')
    print(f'Device settings count: {device_settings_count}')
    print(f'Networks count: {network_count}')
    print(f'Networks settings count: {network_settings_count}')
    print(f'Total settings: {org_settings_count + device_settings_count + network_settings_count}')
    return org_settings_count, device_count, device_settings_count, network_count, network_settings_count
    

def get_orgs(orgid):
    """Get list of organizations accessible by the user's Meraki API key
    or resolve orgid to name

    Obtains and prints a list of the Meraki organizations acessible by the
    user's Meraki API key to the CLI (for help purposes) or resolves the
    supplied orgid to organization name.

    :param orgid: Meraki customer organization identifier
    :returns: None or organization name
    """
    # Instantiate a Meraki dashboard API session
    dashboard = meraki.DashboardAPI(
        api_key='',
        base_url=env.meraki_base_api_url,
        output_log=True,
        log_file_prefix=os.path.basename(__file__)[:-3],
        log_path=log_path,
        print_console=False
    )
    
    if orgid == 'ALL':
        # Get Meraki orgids the API_KEY has access to; print list
        organizations = dashboard.organizations.getOrganizations()

        # Iterate through list of orgs
        print('This API_KEY has access to the following Meraki Orgs:')
        for org in organizations:
            org_id = org['id']
            org_name = org['name']
            print(f'OrgId: {org_id:24} - {org_name}')
    else:
        orginfo = dashboard.organizations.getOrganization(orgid)
        org_name = orginfo['name']
        return org_name


def get_runtime_args():
    """Get user inputs for runtime options

    Uses ArgumentParser to read user CLI inputs and arguments.
    Validates user inputs and requirements.

    :returns: args as user arguments
    """
    parser = argparse.ArgumentParser(description='List available Meraki OrgIds or Execute data collection of settings into git repo.')
    subparsers = parser.add_subparsers(help='Help for subcommand', dest='command')

    listorgs = subparsers.add_parser('listorgs', help='Show Meraki Organizations currently available to the API_KEY - helpful in determining which orgs to collect into git repo')
    
    estimatescan = subparsers.add_parser('estimatescan', help='Estimate length of time to scan Meraki settings for Organization Id identified')
    estimatescan.add_argument('orgid', type=int, help='A Meraki Organization Id (orgid) identifing org to scan')

    getsettings = subparsers.add_parser('getsettings', help='Get Meraki settings for Organization Ids (orgids) identified - archive into git repo')
#    getsettings.add_argument('orgid', metavar='N', type=int, nargs='+', help='1 or more Meraki Organization Ids (orgids) identifing org(s) to archive in git repo')
    getsettings.add_argument('orgid', type=int, help='a Meraki Organization Id (orgid) identifing org to archive in git repo')

    args = parser.parse_args()

    if args.command == None:
        parser.print_help()

    return args


def save_data(file, data, path=''):
    """Helper function to save data to JSON and/or YAML output files

    :param file: filename to save data as
    :param data: data to be saved
    :param path: directory path for file of data to be save in
    :returns: None
    """
    if path and path[-1] != '/':  # add trailing slash if missing
        path += '/'
    if data:  # check if there is actually data
        proceed_saving = False
        # Check if config same as a default file, or null rfProfileId for getDeviceWirelessRadioSettings
        if type(data) == dict and set(data.keys()) == {'rfProfileId', 'serial'}:
            if data['rfProfileId']:
                proceed_saving = True
        elif data not in DEFAULT_CONFIGS:
            proceed_saving = True

        if proceed_saving:
            if env.backup_format in ('both', 'json'):
                with open(f'{path}{file}.json', 'w') as fp:
                    json.dump(data, fp, indent=4)
            if env.backup_format in ('both', 'yaml'):
                with open(f'{path}{file}.yaml', 'w') as fp:
                    yaml.dump(data, fp, explicit_start=True, default_flow_style=False, sort_keys=False)


def update_org_scan_log(org_id):
    """Update org-specific webpage's scan log table - derived from 'git log'

    Updates the organization-specific webpage (index.html) scan log table.
    Extracts data from 'git log' and turns into HTML table output

    :param org_id: Meraki organization identifier
    :returns: None
    """
    os.chdir(f'{env.meraki_base_path}/{str(org_id)}/settings/')
    gitcommits = subprocess.run("git log -n 11 --pretty=oneline", shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True)
    gitcommitlist = gitcommits.stdout.splitlines()
    gitcommitlist.pop()

    tablerows = ""
    for commit in gitcommitlist:
        #print(commit)
        matchCommit = re.search(r"^(\w+) \'(.*)\'$", commit, re.M)
        tablerow = f'''							<tr>
								<td>{matchCommit.group(1)}</td>
								<td>{matchCommit.group(2)}</td>
							</tr>
'''
        #print(tablerow)
        tablerows += tablerow
    
    orgwebpage = f'{env.web_publishing_dir}/orgs/{org_id}/index.html'
    with open(orgwebpage, "r") as inputfile:
        filecontent = inputfile.read()
    scantable_regex = r'(<!-- Insert Settings Scans Record HERE -->.*?)</tbody'
    matchScanTable = re.search(scantable_regex, filecontent, re.DOTALL)
    replacementScanTable = f'''<!-- Insert Settings Scans Record HERE -->\n{tablerows}\n                                </tbody> 
'''
    replacementhtml = filecontent.replace(matchScanTable.group(1), replacementScanTable)

    with open(orgwebpage, "w") as outputfile:
        outputfile.write(replacementhtml)


def update_org_scans_page(org_id, org_name, date_time_verbose, netcount, devicecount, settingscount):
    """Updates the org-specific webpage with counters and scan-time info

    Updates the organization-specific webpage (index.html) with counters 
    of networks, devices, settings and scan-time info.

    :param org_id: Meraki organization identifier
    :param org_name: Meraki organization name
    :param date_time_verbose: Nicely formatted date-time output for web report
    :param netcount: Count of networks in organization
    :param devicecount: Count of devices in organization
    :param settingscount: Count of Meraki settings archived
    :returns: None
    """
    print("Updating org-specific webpage")
    if not os.path.exists(f'{env.web_publishing_dir}/orgs/{org_id}'): os.makedirs(f'{env.web_publishing_dir}/orgs/{org_id}') 
    # Read in org-specific page
    orgwebpage = f'{env.web_publishing_dir}/orgs/{org_id}/index.html'
    if not os.path.exists(orgwebpage):
        print(os.path.realpath(__file__))
        print(os.path.basename(__file__))
        orgtemplate = os.path.realpath(__file__).replace(os.path.basename(__file__), 'html/templ-org-index.html')
        print(orgtemplate)
        shutil.copyfile(orgtemplate, orgwebpage) 

    with open(orgwebpage, "r") as inputfile:
        filecontent = inputfile.read()
        #print (filecontent)
    scandate_regex = r'(<!-- Last Scan DateTime -->.*?)<br>'
    org_regex = r'(<!-- OrgId -->.*<!-- OrgName -->.*?)</td>'
    netcount_regex = r'(<!-- NetworksLastCount -->.*?)</td>'
    devcount_regex = r'(<!-- DevicesLastCount -->.*?)</td>'
    settingscount_regex = r'(<!-- SettingsLastCount -->.*?)</td>'
    matchScanDateTime = re.search(scandate_regex, filecontent, re.DOTALL)
    matchOrg = re.search(org_regex, filecontent, re.DOTALL)
    matchNet = re.search(netcount_regex, filecontent, re.DOTALL)
    matchDev = re.search(devcount_regex, filecontent, re.DOTALL)
    matchSetting = re.search(settingscount_regex, filecontent, re.DOTALL)

    replacementScanDate = f'''<!-- Last Scan DateTime -->{date_time_verbose}'''
    replacementOrg = f'''<!-- OrgId -->{org_id}<br>
                                                            <!-- OrgName -->{org_name}'''
    replacementNet = f'''<!-- NetworksLastCount -->{netcount}'''
    replacementDev = f'''<!-- DevicesLastCount -->{devicecount}'''
    replacementSettings = f'''<!-- SettingsLastCount -->{settingscount}'''
    replacementhtml = filecontent.replace(matchScanDateTime.group(1), replacementScanDate)
    replacementhtml = replacementhtml.replace(matchOrg.group(1), replacementOrg)
    replacementhtml = replacementhtml.replace(matchNet.group(1), replacementNet)
    replacementhtml = replacementhtml.replace(matchDev.group(1), replacementDev)
    replacementhtml = replacementhtml.replace(matchSetting.group(1), replacementSettings)

    with open(orgwebpage, "w") as outputfile:
            outputfile.write(replacementhtml)



####### Module Function definitions above
########################################
####### Main function definition below

def main(args):
    global date_time
    global date_time_verbose
    now = datetime.now() # current date and time
    date_time = now.strftime("%Y%m%d-%H%M%S")
    date_time_verbose = now.strftime("%A, %B %d, %Y at %H:%M:%S %Z")
    
    if args.command == 'listorgs':
        get_orgs('ALL')
    elif args.command == 'getsettings':
        start_time = datetime.now()
        if os.environ.get('MERAKI_DASHBOARD_API_KEY'):
            api_key = os.environ.get('MERAKI_DASHBOARD_API_KEY')
        else:
            api_key = API_KEY
        org_name = get_orgs(args.orgid)
        check_orgdir_status(args.orgid)
        check_git_status(args.orgid, org_name)
        archive_settings(api_key, args.orgid, None)
        commit_processed_files(args.orgid)
        org_settings_count, device_count, device_settings_count, network_count, network_settings_count = get_metrics(args.orgid)
        update_org_scans_page(args.orgid, org_name, date_time_verbose, network_count, device_count, org_settings_count + network_settings_count + device_settings_count)
        update_org_scan_log(args.orgid)

        end_time = datetime.now()
        print(f'\nScript complete, total runtime {end_time - start_time}')
    elif args.command == 'estimatescan':
        estimate_backup('', args.orgid, '')


if __name__ == '__main__':
    args = get_runtime_args()
    main(args)
