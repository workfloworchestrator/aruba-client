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

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ArubaConfig(BaseSettings):
    """Configuration for the Aruba Central MSP client, read from ARUBA_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="ARUBA_")

    MSP_CLIENT_ID: SecretStr
    MSP_CLIENT_SECRET: SecretStr
    MSP_WORKSPACE_ID: SecretStr
    GREENLAKE_OAUTH_URL: str
    BASE_URL: str = "https://de3.api.central.arubanetworks.com"
