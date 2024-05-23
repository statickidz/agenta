import os
import logging
from typing import Optional, Any

from agenta.sdk.utils.globals import set_global
from agenta.client.backend.client import AgentaApi
from agenta.client.exceptions import APIRequestError


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class AgentaSingleton:
    """Singleton class to save all the "global variables" for the sdk."""

    _instance = None
    setup = None
    config = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = super(AgentaSingleton, cls).__new__(cls)
        return cls._instance

    @property
    def client(self):
        """Builds sdk client instance.

        Returns:
            AgentaAPI: instance of agenta api backend
        """

        return AgentaApi(base_url=self.host + "/api", api_key=self.api_key)

    def init(
        self,
        app_name: Optional[str] = None,
        base_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_id: Optional[str] = None,
        app_id: Optional[str] = None,
        host: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Main function to initialize the singleton.

        Initializes the singleton with the given `app_name`, `base_name`, and `host`.
        If any of these arguments are not provided, the function will look for them
        in environment variables.

        Args:
            app_name (Optional[str]): Name of the application. Defaults to None.
            base_name (Optional[str]): Base name for the setup. Defaults to None.
            api_key (Optional[str]): API Key to use with the host. Defaults to None.
            base_id (Optional[str]): Base ID for the setup. Defaults to None.
            app_id (Optional[str]): App ID. Defaults to None.
            host (Optional[str]): Host name of the backend server. Defaults to "http://localhost".
            kwargs (Any): Additional keyword arguments.

        Raises:
            ValueError: If `app_name`, `base_name`, or `host` are not specified either as arguments
            or in the environment variables.
        """

        self.app_name = app_name or os.environ.get("AGENTA_APP_NAME")
        self.base_name = base_name or os.environ.get("AGENTA_BASE_NAME")
        self.api_key = api_key or os.environ.get("AGENTA_API_KEY")
        self.base_id = base_id or os.environ.get("AGENTA_BASE_ID")
        self.app_id = app_id or os.environ.get("AGENTA_APP_ID")
        self.host = host or os.environ.get("AGENTA_HOST", "http://localhost")

        if not self.app_id and (not self.app_name or not self.base_name):
            print(
                f"Warning: Your configuration will not be saved permanently since app_name and base_name are not provided."
            )

        if not self.base_id and self.app_name and self.base_name:
            try:
                self.app_id = self.get_app(self.app_name)
                self.base_id = self.get_app_base(self.app_id, self.base_name)
            except Exception as ex:
                raise APIRequestError(
                    f"Failed to get base id and/or app_id from the server with error: {ex}"
                )

        self.variant_id = os.environ.get("AGENTA_VARIANT_ID")
        self.variant_name = os.environ.get("AGENTA_VARIANT_NAME")
        self.config = Config(base_id=self.base_id, host=self.host)

    def get_app(self, app_name: str) -> str:
        apps = self.client.apps.list_apps(app_name=app_name)
        if len(apps) == 0:
            raise APIRequestError(f"App with name {app_name} not found")

        app_id = apps[0].app_id
        return app_id

    def get_app_base(self, app_id: str, base_name: str) -> str:
        bases = self.client.bases.list_bases(app_id=app_id, base_name=base_name)
        if len(bases) == 0:
            raise APIRequestError(f"No base was found for the app {app_id}")
        return bases[0].base_id

    def get_current_config(self):
        """
        Retrieves the current active configuration
        """

        if self._config_data is None:
            raise RuntimeError("AgentaSingleton has not been initialized")
        return self._config_data


class Config:
    def __init__(self, base_id, host):
        self.base_id = base_id
        self.host = host

        if base_id is None or host is None:
            self.persist = False
        else:
            self.persist = True

    @property
    def client(self):
        """Builds sdk client instance.

        Returns:
            AgentaAPI: instance of agenta api backend
        """

        sdk_client = SDKClient(api_key=self.api_key, host=self.host)  # type: ignore
        return sdk_client._build_sdk_client()

    def register_default(self, overwrite=False, **kwargs):
        """alias for default"""
        return self.default(overwrite=overwrite, **kwargs)

    def default(self, overwrite=False, **kwargs):
        """Saves the default parameters to the app_name and base_name in case they are not already saved.
        Args:
            overwrite: Whether to overwrite the existing configuration or not
            **kwargs: A dict containing the parameters
        """
        self.set(
            **kwargs
        )  # In case there is no connectivity, we still can use the default values
        try:
            self.push(config_name="default", overwrite=overwrite, **kwargs)
        except Exception as ex:
            logger.warning(
                "Unable to push the default configuration to the server." + str(ex)
            )

    def push(self, config_name: str, overwrite=True, **kwargs):
        """Pushes the parameters for the app variant to the server
        Args:
            config_name: Name of the configuration to push to
            overwrite: Whether to overwrite the existing configuration or not
            **kwargs: A dict containing the parameters
        """
        if not self.persist:
            return
        try:
            self.client.configs.save_config(
                base_id=self.base_id,
                config_name=config_name,
                parameters=kwargs,
                overwrite=overwrite,
            )
        except Exception as ex:
            logger.warning(
                "Failed to push the configuration to the server with error: " + str(ex)
            )

    def pull(
        self, config_name: str = "default", environment_name: Optional[str] = None
    ):
        """Pulls the parameters for the app variant from the server and sets them to the config"""
        if not self.persist and (
            config_name != "default" or environment_name is not None
        ):
            raise Exception(
                "Cannot pull the configuration from the server since the app_name and base_name are not provided."
            )
        if self.persist:
            try:
                if environment_name:
                    config = self.client.configs.get_config(
                        base_id=self.base_id, environment_name=environment_name
                    )

                else:
                    config = self.client.configs.get_config(
                        base_id=self.base_id,
                        config_name=config_name,
                    )
            except Exception as ex:
                logger.warning(
                    "Failed to pull the configuration from the server with error: "
                    + str(ex)
                )
        try:
            self.set(**{"current_version": config.current_version, **config.parameters})
        except Exception as ex:
            logger.warning("Failed to set the configuration with error: " + str(ex))

    def all(self):
        """Returns all the parameters for the app variant"""
        return {
            k: v
            for k, v in self.__dict__.items()
            if k
            not in ["app_name", "base_name", "host", "base_id", "api_key", "persist"]
        }

    # function to set the parameters for the app variant
    def set(self, **kwargs):
        """Sets the parameters for the app variant

        Args:
            **kwargs: A dict containing the parameters
        """
        for key, value in kwargs.items():
            setattr(self, key, value)


def init(app_name=None, base_name=None, **kwargs):
    """Main function to be called by the user to initialize the sdk.

    Args:
        app_name: _description_. Defaults to None.
        base_name: _description_. Defaults to None.
    """

    singleton = AgentaSingleton()

    singleton.init(app_name=app_name, base_name=base_name, **kwargs)
    set_global(setup=singleton.setup, config=singleton.config)
