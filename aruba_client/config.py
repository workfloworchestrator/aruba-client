# Copyright 2019-2025 SURF.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

UxiRegion = Literal["us-production", "eu-production"]


class ArubaConfig(BaseSettings):
    """Configuration for the Aruba Central MSP client, read from ARUBA_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="ARUBA_")

    MSP_CLIENT_ID: SecretStr
    MSP_CLIENT_SECRET: SecretStr
    MSP_WORKSPACE_ID: SecretStr
    GREENLAKE_OAUTH_URL: str
    BASE_URL: str = "https://de3.api.central.arubanetworks.com"


class UxiConfig(BaseSettings):
    """Configuration for the HPE Aruba UXI client, read from ARUBA_UXI_* environment variables.

    UXI is authorised by its own GreenLake API client (one bound to the "User Experience
    Insight" service), not by the Aruba Central MSP credentials. ``REGION`` has no default
    on purpose: a wrong region is answered with a 403 or another region's (empty) data
    rather than a clear error, whereas a missing variable fails at startup.
    """

    model_config = SettingsConfigDict(env_prefix="ARUBA_UXI_")

    CLIENT_ID: SecretStr
    CLIENT_SECRET: SecretStr
    REGION: UxiRegion
    OAUTH_TOKEN_URL: str = "https://sso.common.cloud.hpe.com/as/token.oauth2"
    BASE_URL: str = "https://api.capenetworks.com/networking-uxi/v1alpha1"
