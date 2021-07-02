Meraki Settings Archive & Differ
=====================================

The Meraki Settings Archive & Differ project extracts Meraki device settings from the Meraki Dashboard API, stores as JSON files in a local git repo and creates web pages showing differences betweeen scans in colorized form.

The business driver for developing this was for Cisco customers that may have sophisticated IT Service Management requirements and also use cloud-managed Meraki equipment.  The solution archives the settings into a local git repo allowing for archive and difference analysis.  This solution is the foundation for possible follow-on functionality, such as settings scans for compliance.  As the settings are stored in feature-specific JSON files, it is easy to write JSON Path Queries to check for compliance to your corporate standards or any other compliance framework (eg. HIPAA, PCI/DSS, Basel II/III/IV, FIPS, etc).  Note, the code in the current project does not provide those rules or functionality.  It is expected that Cisco Customer Experience (CX) will be releasing a service that performs the compliance specific function.


## White Papers and References
[DevNet Meraki Dashboard API Docs](https://developer.cisco.com/meraki/api-v1/)
[Meraki Dashboard API Docs](https://documentation.meraki.com/General_Administration/Other_Topics/Cisco_Meraki_Dashboard_API) from Meraki team

## Related Sandbox
[Meraki Always On Sandbox](https://devnetsandbox.cisco.com/RM/Diagram/Index/a9487767-deef-4855-b3e3-880e7f39eadc?diagramType=Topology) - non-reservable, always on
[Meraki Enterprise Sandbox](https://devnetsandbox.cisco.com/RM/Diagram/Index/e7b3932b-0d47-408e-946e-c23a0c031bda?diagramType=Topology) - reservable
[Meraki Small Business Sandbox](https://devnetsandbox.cisco.com/RM/Diagram/Index/aa48e6e2-3e59-4b87-bfe5-7833c45f8db8?diagramType=Topology) - reservable

## Links to DevNet Learning Labs
[Meraki Learning Labs](https://developer.cisco.com/learning/tracks/meraki)

## Solutions on Ecosystem Exchange
[Meraki Ecosystem Exchange solutions](https://developer.cisco.com/ecosystem/solutions/#key=meraki)
