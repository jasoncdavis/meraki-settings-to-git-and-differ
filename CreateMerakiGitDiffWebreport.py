"""Create Meraki Git Diff Web report (CreateMerakiGitDiffWebreport.py)
#                                                                      #
Parses Meraki Git repo for difference and creates a side-by-side diff
web report.  Uses html2diff from 
https://www.npmjs.com/package/diff2html-cli

Defaults to latest commit (HEAD) and previous (HEAD~1), but user can
provide command-line input to request specific diffs by commit hash or
arbitrary extended object reference (HEAD, HEAD~1, etc)

Required command-line inputs:
    list orgid - lists commits in gir for orgid; helpful for deciding 
        which branches to diff
    getdiff FirstCommit SecondCommit - runs diff on FirstCommit and 
        SecondCommit branches, then generates webreport

where -
    orgid - represents Meraki Organization being queried
    FirstCommit - The first commit hash code or HEAD reference - 
        defaults to HEAD
    SecondCommit - The second commit hash code or HEAD reference - 
        defaults to HEAD~1

Required module variables:
None (carried in MerakiNCCMconfig.py parameters file)

Outputs:
    create diff report in web format to web publishing directory 
    (eg. /var/www/html)

"""

__version__ = '1'
__author__ = 'Jason Davis - jadavis@cisco.com'
__license__ = "Cisco Sample Code License, Version 1.1 - https://developer.cisco.com/site/license/cisco-sample-code-license/"


import argparse
import sys
import os
import subprocess
from datetime import datetime
import re
import GMSIGconfig as env
import meraki
import shutil
from inspect import getsourcefile



# Module variables
log_path = "logs"

########################################
####### Module Function definitions

def get_commits(in_args, org_name):
    """List git commits in repo for user reference
    
    Obtains git log output and prints results including commit hashes and messages.

    :param in_args: List of user input args, includes commit references
    :param org_name: Meraki organization name
    :returns: None
    """

    # List git commits for user reference
    os.chdir(f'{env.git_base_path}/{in_args.orgid}/settings/')
    gitcommits = subprocess.run("git log --pretty=oneline", shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True)
    print(f'Git commits for Meraki org id {in_args.orgid} - {org_name} are:\n[-- Commit Hash -----------------------] \'Branch commit message...\'\n{gitcommits.stdout}')


def get_diffs(in_args):
    """Obtains git diff and log output - creates lists of diff components
    
    Extracts difference summaries from 'git log' and performs 'git diff'
    from two input commit references (eg. HEAD and HEAD~2)

    :param in_args: List of user input args, includes commit references
    :returns: Commit dates and lists of addtiions, modifications and
        deletions in git repo
    """
    # Process git logs and git diffs
    os.chdir(env.git_base_path + "/" + in_args.orgid + "/settings/")
    diff_summary1 = subprocess.run(f'git log --pretty=fuller -n 1 {in_args.FirstCommit}', shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True)
    diff_summary2 = subprocess.run(f'git log --pretty=fuller -n 1 {in_args.SecondCommit}', shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True)

    CommitObj = re.search( r'CommitDate: (.*)\n', diff_summary1.stdout )
    CommitObj2 = re.search( r'CommitDate: (.+)\n', diff_summary2.stdout)
    diff_file_list = subprocess.run(f'git diff --name-status {in_args.FirstCommit} {in_args.SecondCommit}', shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True)
    Git_Added = []
    Git_Modified = []
    Git_Deleted = []
    Git_Others = []

    for item in diff_file_list.stdout.splitlines():
        print(item)
        matchObj = re.match( r'(\w+)\s+(.*)', item)
        if matchObj.group(1) == 'A':
            Git_Added.append(matchObj.group(2))
        elif matchObj.group(1) == 'M':
            Git_Modified.append(matchObj.group(2))
        elif matchObj.group(1) == 'D':
            Git_Deleted.append(matchObj.group(2))
        else:
            Git_Others.append(matchObj.group(2))

    return (CommitObj.group(1), CommitObj2.group(1), Git_Added, Git_Modified, Git_Deleted, Git_Others)


def get_orgs(orgid):
    """Obtains and prints a list Meraki organization ids and names
    accessible by the API Key or cross-references organization id to name.
    
    Performs a look up for all Meraki organizations accessible by the API
    key when 'ALL' is passed as input or performs an org id to name lookup
    if a single org id is passed as input.

    :param orgid: Meraki organization identifier
    :returns: printed list of organization ids and names or a string of
        organization name associated to org id
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


def check_environment():
    """Checks the environment for proper web publishing template
    
    Checks the environment to ensure the proper diff2html template
    file is in the proper web-publishing location.  If not, it
    copies the file as necessary

    :returns: None [creates file outputs to web publishing dir]
    """
    print(f'Checking web publilshing directory template.\n')
    diffhwt = f'{env.web_publishing_dir}/diff-hwt.html'
    if not os.path.exists(diffhwt):
        hwttemplate = os.path.realpath(__file__).replace(os.path.basename(__file__), 'html/diff-hwt.html')
        shutil.copyfile(hwttemplate, diffhwt) 


def create_websection(cli_args, items, mode, diff1_datetime, diff2_datetime):
    """Creates a difference webpage report of a Meraki setting
    
    Creates a webpage report showing differences between two commits for
    a specific Meraki setting.  Uses the diff2html open source project
    to process the git repo references and turn them into HTML.

    :param cli_args: List of user input args, includes commit references
    :param items: Meraki setting for processing (eg. orgDevices)
    :param diff1_datetime: Date-time of first commit reference
    :param diff2_datetime: Date-time of second commit reference
    :returns: None [creates file outputs to web publishing dir]
    """
    os.chdir(env.git_base_path + "/" + cli_args.orgid + "/settings/")
    print(f'Creating web section for {mode}\n')
    for item in items:
        gititem = item
        if item.startswith('networks') or item.startswith('devices'):
            item = item.replace('/', '-')
        print(f'...working on item {gititem}')
        diffcmd = f'diff2html -s side --hwt {env.web_publishing_dir}/diff-hwt.html -F "{env.web_publishing_dir}/orgs/{cli_args.orgid}/reports/{date_time}/{item}.html" -- -W {cli_args.FirstCommit} {cli_args.SecondCommit} -- "{gititem}"'
        #print(diffcmd)
        subprocess.run(diffcmd, shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True)
        # Read in the file
        with open(f'{env.web_publishing_dir}/orgs/{cli_args.orgid}/reports/{date_time}/{item}.html', 'r') as file:
            filedata = file.read()

        # Replace target strings
        filedata = filedata.replace('###COMMITA###', cli_args.FirstCommit + ' scan datetime ' + diff1_datetime)
        filedata = filedata.replace('###COMMITB###', cli_args.SecondCommit + ' scan datetime ' + diff2_datetime)
        filedata = filedata.replace('###OBJECT###', gititem)
        filedata = filedata.replace('###REPORTDATE###', date_time)

        # Write the file out again
        with open(f'{env.web_publishing_dir}/orgs/{cli_args.orgid}/reports/{date_time}/{item}.html', 'w') as file:
            file.write(filedata)


def create_difflist_webpage(cli_args, diff1_datetime, diff2_datetime):
    """Creates difference list date-specific webpage
    
    Creates a date-specific webpage report showing difference list as a 
    summary across two different commits (eg. HEAD and HEAD~2)
    
    :param cli_args: List of user input args, includes commit references
    :param diff1_datetime: Date-time of first commit reference
    :param diff2_datetime: Date-time of second commit reference
    :returns: List of changed items
    """
    files = os.listdir(f'{env.web_publishing_dir}/orgs/{cli_args.orgid}/reports/{date_time}')
    changeditems = []
    for item in sorted(files):
        setting = item.split(".")[0]
        settingpath = setting.replace('-','/', 1)
        settingpath = settingpath.replace('-network','/network', 1)
        settingpath = settingpath.replace('-device','/device', 1)


        htmlitem = f"""<a href="{env.web_url}/orgs/{cli_args.orgid}/reports/{date_time}/{item}">{settingpath}</a><br>"""
        changeditems.append(htmlitem)

    #print(f'The following settings/files were affected in last scan of\ncommit {cli_args.FirstCommit} at {diff1_datetime} with\ncommit {cli_args.SecondCommit} at {diff2_datetime}:\n\n{files}')
    newline = '\n'
    htmlpage = f"""<html>
<head></head>
<body><br><h1>Scan results</h1></p>
<p><h2>The following settings/files were affected in last scan of<br>
commit {cli_args.FirstCommit} at {diff1_datetime} with<br>
commit {cli_args.SecondCommit} at {diff2_datetime}:</h2><br>
<br>{newline.join(changeditems)}</p></body>
</html>"""
    with open(f'{env.web_publishing_dir}/orgs/{cli_args.orgid}/reports/{date_time}.html', 'w') as file:
        file.write(htmlpage)
    return newline.join(changeditems)


def create_diffitems_webpages(cli_args, diff1_datetime, diff2_datetime, git_adds, git_modifieds, git_deletes, git_others):
    """Creates Meraki setting-specific difference report as a webpage.
    
    Takes the git difference data as input, creates date-specific reporting
    directory and calls other functions to create Meraki setting-
    specific web pages (diff reports) in a per-scan date directory

    :param cli_args: List of user input args, includes commit references
    :param diff1_datetime: Date-time of first commit reference
    :param diff2_datetime: Date-time of second commit reference
    :param get_adds: list of git repo additions among commit references
    :param get_modifieds: list of git repo modifications among commit 
        references
    :param get_deletes: list of git repo deletions among commit references
    :returns: None; calls other functions
    """

    # Iterates the git adds, modifications, deletions and unknowns to create diff web reports
    # Create a directory for the report run
    os.makedirs(env.web_publishing_dir + '/orgs/' + cli_args.orgid + '/reports/' + date_time) 
    create_websection(cli_args, git_adds, 'Additions', diff1_datetime, diff2_datetime)
    create_websection(cli_args, git_modifieds, 'Modifications', diff1_datetime, diff2_datetime)
    create_websection(cli_args, git_deletes, 'Deletions', diff1_datetime, diff2_datetime)
    #create_websection(cli_args, git_others, 'Other Changes', diff1_datetime, diff2_datetime)


def parse_input_arguments():
    """Parses and validates user's input arguments
    
    Parses and validates user's input arguments using ArgumentParser
    module.  Provides help and input hints.

    :returns: List of input arguments verified and formatted
    """

    # Parse input arguments and provide user a method to list commits for help
    parser = argparse.ArgumentParser(description='Create Meraki git diff web reports or lists available commits based on OrgId.')
    subparsers = parser.add_subparsers(help='Help for subcommand', dest='command')

    listorgs = subparsers.add_parser('listorgs', help='Show Meraki Organizations currently in git repo - helpful in determining which orgs and commits to diff')
    
    listcommits = subparsers.add_parser('listcommits', help='Show commit entries - helpful in determining which commits to diff')
    listcommits.add_argument('orgid', help='Meraki Organization Id (orgid) identifing org archived in git repo')
    
    gendiffs = subparsers.add_parser('getdiff', help='Scan for diffs and report against Meraki Organization Id (orgid) archived in git repo')
    gendiffs.add_argument('orgid', help='Meraki Organization Id (orgid) identifing org archived in git repo')
    gendiffs.add_argument('FirstCommit', nargs='?', help='Commit to compare, or HEAD~1, is assumed', default='HEAD~1')
    gendiffs.add_argument('SecondCommit', nargs='?', help='Another commit to compare against, or HEAD, is assumed', default='HEAD')

    args = parser.parse_args()
    if args.command == None:
        parser.print_help()
        sys.exit()
    else:
        return args


def update_lastestdiff_tab(orgid, args, diff1_datetime, diff2_datetime, changeditems):
    """Updates Latest difference report tab of main org's report page
    
    Takes the Meraki organization id, user input arguments, commit
    date-time values and changed items list to update the organization's
    main summary webpage, specifically the latest diff tab.

    :param orgid: Meraki organization identifier
    :param args: List of user input args, includes commit references
    :param diff1_datetime: Date-time of first commit reference
    :param diff2_datetime: Date-time of second commit reference
    :param changeditems: List of changed items in last settings diff scan
    :returns: None; updates/creates files
    """
    # Update Latest Diff tab on org's index.html summary report webpage
    os.chdir(env.web_publishing_dir + '/orgs/' + orgid)
    
    # Read org summary page, update the Report generation history table
    summarywebpage = f'{env.web_publishing_dir}/orgs/{orgid}/index.html'
    with open(summarywebpage, 'r') as inputfile:
        webpage = inputfile.read()
    # TODO - What if this is the FIRST time we're running it and we never had an index.html yet?  Pull template and modify
    
    rowplaceholder_regex = r'<!-- START Last Diffs Report Summary table -->(.*?)<!-- END Last Diffs Report Summary table -->'
    match_priordata = re.search(rowplaceholder_regex, webpage, re.S | re.M)
    newrow_replacement = f'''<!-- START Last Diffs Report Summary table -->
<h1>Scan results</h1></p>
<p><h2>The following settings/files were affected in last scan of<br>
commit {args.FirstCommit} at {diff1_datetime} with<br>
commit {args.SecondCommit} at {diff2_datetime}:</h2><br>
{changeditems}
<!-- END Last Diffs Report Summary table -->'''

    if match_priordata.group(1) == '\n':
        replacementhtml = webpage.replace(match_priordata.group(0), newrow_replacement)
    else:
        replacementhtml = webpage.replace(match_priordata.group(1), newrow_replacement)
    
    with open(summarywebpage, "w") as outputfile:
        outputfile.write(replacementhtml)


def update_org_summary(orgid, args, diff1_datetime, diff2_datetime):
    """Updates main org's summary report page
    
    Takes the Meraki organization id, user input arguments, commit
    date-time values to update the organization's main summary webpage, 
    specifically the list of difference scans/reports.

    :param orgid: Meraki organization identifier
    :param args: List of user input args, includes commit references
    :param diff1_datetime: Date-time of first commit reference
    :param diff2_datetime: Date-time of second commit reference
    :returns: None; updates/creates files
    """

    # Update first tab on org index.html and the Diff table 
    os.chdir(f'{env.web_publishing_dir}/orgs/{str(orgid)}')
    if os.path.exists('DBContent-Latest.html'): os.remove('DBContent-Latest.html')
    os.symlink(f'reports/{date_time}.html', 'DBContent-Latest.html')

    # Read org summary page, update the Report generation history table
    summarywebpage = f'{env.web_publishing_dir}/orgs/{orgid}/index.html'
    try:
        with open(summarywebpage, 'r') as inputfile:
            webpage = inputfile.read()
    except FileNotFoundError:
        shutil.copyfile(f'{os.path.dirname(getsourcefile(lambda:0))}/html/templ-org-index.html', 'index.html')
        with open(summarywebpage, 'r') as inputfile:
            webpage = inputfile.read()
    
    # If args.FirstCommit or args.SecondCommit are using HEAD.* references, change to commit hash value
    os.chdir(f'{env.git_base_path}/{str(orgid)}/settings')
    if args.FirstCommit.startswith( 'HEAD' ):
        firstcommithash = subprocess.run(f'git rev-parse {args.FirstCommit}', shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True).stdout.rstrip()
    else:
        firstcommithash = args.FirstCommit
    
    if args.SecondCommit.startswith( 'HEAD' ):
        secondcommithash = subprocess.run(f'git rev-parse {args.SecondCommit}', shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True).stdout.rstrip()
    else:
        secondcommithash = args.SecondCommit

    rowplaceholder = r'<!-- Insert New Diff Record as Table Row HERE -->'
    newrow_replacement = f'''<!-- Insert New Diff Record as Table Row HERE -->
    			<tr>
				    <td><a href="reports/{date_time}.html">{date_time_verbose}</a></td>
				    <td>{firstcommithash}</td>
				    <td>{diff1_datetime}</td>
				    <td>{secondcommithash}</td>
				    <td>{diff2_datetime}</td>
			    </tr>'''
    replacementhtml = webpage.replace(rowplaceholder, newrow_replacement)
    
    with open(summarywebpage, "w") as outputfile:
        outputfile.write(replacementhtml)


########################################
####### Module Main definition

def main():
    # Get user input for orgid to scan from local git repo
    global date_time
    global date_time_verbose
    now = datetime.now() # current date and time
    date_time = now.strftime("%Y%m%d-%H%M%S")
    date_time_verbose = now.strftime("%A, %B %d, %Y at %H:%M:%S %Z")
    args = parse_input_arguments()
    if args.command == 'listorgs':
        print('Please waiting, processing Meraki API data...')
        get_orgs('ALL')
    elif args.command == 'listcommits':
        orgname=get_orgs(args.orgid)
        get_commits(args, orgname)
    elif args.command == 'getdiff':
        print(f'Starting at: {date_time_verbose}')
        # Run diffing function, get_diffs
        (diff1_datetime, diff2_datetime, git_adds, git_modifieds, git_deletes, git_others) = get_diffs(args)
        
        # Create the individual diff items webpages (in date-specific subordinate folders) and date-specific list webpage
        # /var/www/html/DevNetDashboards/MerakiGit/orgs/<org_id>/reports/YYYYMMDD-HHMMSS.html
        check_environment()
        create_diffitems_webpages(args, diff1_datetime, diff2_datetime, git_adds, git_modifieds, git_deletes, git_others)
        changeditems = create_difflist_webpage(args, diff1_datetime, diff2_datetime)

        # Update org summary page (first tab of index.html)
        update_org_summary(args.orgid, args, diff1_datetime, diff2_datetime)
        # Update org summary page (second tab of index.html)
        update_lastestdiff_tab(args.orgid, args, diff1_datetime, diff2_datetime, changeditems)


if __name__ == '__main__':
    start_time = datetime.now()
    main()
    end_time = datetime.now()
    print(f'\nScript complete, total runtime {end_time - start_time}')