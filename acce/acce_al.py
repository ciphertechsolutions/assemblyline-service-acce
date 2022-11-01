"""
Overview
========

Scan payloads using ACCE

"""
import hashlib
import json
from os import path
import re
import zipfile
from io import BytesIO
from json import JSONDecodeError
from time import sleep
from typing import Dict, List, Tuple
from os.path import isdir, isfile, basename

import requests
from requests.models import Response, Request

from assemblyline_v4_service.common.base import ServiceBase
from assemblyline_v4_service.common.result import Result, ResultSection, BODY_FORMAT

class InvalidConfiguration(Exception):
    """Exception class for when an ACCE configuration is not valid, such as no base_url or api_key"""
    pass

class ACCE(ServiceBase):

    def start(self) -> None:
        self.base_url = self.config.get("base_url")
        if not self.base_url:
            raise InvalidConfiguration("base_url was not set.")
        self.api_key_default = self.config.get("api_key")

    def execute(
        self, request: Request
    ):
        """
        Scan payloads using ACCE
        """

        result = Result()
        errors = []
        api_key = request.get_param("api_key")
        if not api_key:
            if not self.api_key_default:
                raise InvalidConfiguration("No api_key with request or as default")
            else:
                api_key = self.api_key_default
        mwcp_legacy = request.get_param("mwcp_legacy")
        get_artifacts = request.get_param("get_artifacts")
        submission_url = f"{self.base_url}/api/v1/submissions"
        filename = basename(request.file_path)
        if isinstance(filename, bytes):
            filename = filename.decode()
        

        if api_key is None:
            self.log.error('In order to upload files to ACCE, you must have a valid API key configured.')
            return None

        if isdir(request.file_path):
            self.log.error('The path specified appears to be a directory and not a file.')
            return None
        elif not isfile(request.file_path):
            self.log.error('The file specified for upload does not exist.')
            return None

        self.log.debug(f'Reading {basename(request.file_path)} into memory.')
        with open(request.file_path, "rb") as f:
            file_data = f.read()
        files = {"sample": (filename, file_data)}
        auth_header = {'Authorization': f'Token {api_key}'}
        response: Response = requests.post(
            submission_url, data={}, files=files, headers=auth_header,
        )
        if response.status_code != 201:
            self.log.error(f"Invalid status code {response.status_code} received from file upload")
            response_body = _safe_get_json(response)
            if response_body.get("error", None):
                self.log.error(response_body.get("error"))
            return None
        results = _safe_get_json(response)
        if results.get("error", None):
            errors.append(results["error"])
            
        results_url = results.get("result")
        submission_id = results.get("uuid")
        if not (results_url and submission_id):
            errors.append(
                "Results url/submission_id not returned from original request, unable to retrieve results"
            )
        
        results, poll_errors = self._poll_for_results(results_url, auth_header, mwcp_legacy)
        errors.extend(poll_errors)
        if get_artifacts:
            self._get_submission_artifacts(request, auth_header, submission_id)

        result.add_section(ResultSection(f"ACCE Detailed Results",
                                         body_format=BODY_FORMAT.JSON,
                                         body=json.dumps(results)))
        request.result = result

    def _poll_for_results(self, url: str, auth_header: dict, mwcp_legacy: bool) -> Tuple[Dict, List[str]]:
        """
        Polls ACCE submission , waiting for results to finish processing
        Stops polling if:
            1) max_attempts is reached
            2) ACCE returns a non 200 status code
            3) ACCE returns an error in response body
        Returns dict of results and list of errors
        """
        errors = []
        max_poll_attempts = self.config.get("max_poll_attempts", 20)
        poll_delay = self.config.get("poll_delay", 20)
        for _ in range(max_poll_attempts):
            result_req: Response = requests.get(
                url, headers=auth_header, params={"legacy": mwcp_legacy}
            )
            result_data = _safe_get_json(result_req)

            if result_data.get("status") in ("running", "pending"):
                pass
            elif result_req.status_code != 200 or "error" in result_data:
                if "error" in result_data:
                    errors.append(result_data["error"])
                if result_req.status_code != 200:
                    errors.append(
                        f"Bad status code {result_req.status_code} from results polling"
                    )
                return result_data, errors
            elif "result" in result_data:
                return result_data.get("result"), errors

            sleep(poll_delay)
        errors.append(
            f"Max poll attempts ({max_poll_attempts}) exceeded after waiting {max_poll_attempts * poll_delay} seconds"
        )
        return result_data, errors

    def _get_submission_artifacts(
        self, request, auth_header, submission_id
    ):
        """
        Downloads artifacts produced by ACCE processing
        Extracts artifacts from artifact zip
        Returns a list of artifacts and a list of errors
        """
        errors = []

        response: Response = requests.get(f"{self.base_url}/api/v1/submissions/{submission_id}/result/archive", headers=auth_header)
        if response.status_code != 200:
            self.log.error('Failed to get archive from ACCE.')
        content = BytesIO(response.content)
        if not zipfile.is_zipfile(content):
            errors.append(
                "Expected content to be a zipfile, but zipfile.is_zipfile() returned False"
            )
        else:
            zip = zipfile.ZipFile(content)
            artifact_names = [
                x for x in zip.namelist() if re.search("^extracted_components/.+$", x)
            ]
            for artifact_name in artifact_names:
                artifact_bytes = zip.read(artifact_name, pwd=b"infected")
                hasher = hashlib.sha256()
                hasher.update(artifact_bytes)
                artifact_path = path.join(self.working_directory, hasher.hexdigest())
                with open(artifact_path, "wb") as artifact:
                    artifact.write(artifact_bytes)
                request.add_extracted(artifact_path, hasher.hexdigest(), f'Extracted from {request.sha256}')

def _safe_get_json(req: requests.Response) -> Dict:
    """
    Safely get a request JSON response

    Returns a dict with an error message if decoding fails
    """
    try:
        return req.json()
    except JSONDecodeError as e:
        return {"error": [e]}