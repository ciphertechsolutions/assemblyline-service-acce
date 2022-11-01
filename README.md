# ACCE Service

This Assemblyline service submits ACCE web API and provides the results.  All files should be submitted and ACCE will decide which will be processed, with unprocessed files not counting against your quota.

**NOTE**: This service **requires** you to have your own API key. It is **not** preinstalled during a default installation.

## Execution

This service uploads the provided file to ACCE and returns the results (if any).

Because this service queries an external API, if selected by the user, it will prompt the user and notify them that their file or metadata related to their file will leave our system.

## Dependencies

This service does not need any additional dependencies, just requests to call the API and AssemblyLine service which are both already available.
