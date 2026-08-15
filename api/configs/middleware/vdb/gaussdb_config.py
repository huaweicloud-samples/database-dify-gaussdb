from pydantic import Field, PositiveInt
from pydantic_settings import BaseSettings


class GaussDBConfig(BaseSettings):
    """
    Configuration settings for GaussDB
    """

    GAUSSDB_HOST: str | None = Field(
        description="Hostname or IP address of the GaussDB server(e.g., 'localhost')",
        default=None,
    )

    GAUSSDB_PORT: PositiveInt = Field(
        description="Port number on which the GaussDB server is listening (default is 19995)",
        default=19995,
    )

    GAUSSDB_USER: str | None = Field(
        description="Username for authenticating with the GaussDB database",
        default=None,
    )

    GAUSSDB_PASSWORD: str | None = Field(
        description="Password for authenticating with the GaussDB database",
        default=None,
    )

    GAUSSDB_DATABASE: str | None = Field(
        description="Name of the GaussDB database to connect to",
        default=None,
    )

    GAUSSDB_MIN_CONNECTION: PositiveInt = Field(
        description="Min connection of the GaussDB database",
        default=1,
    )

    GAUSSDB_MAX_CONNECTION: PositiveInt = Field(
        description="Max connection of the GaussDB database",
        default=5,
    )

    GAUSSDB_INDEX_TYPE: str = Field(
        description="Vector index type: 'ivfflat' (<=1024 dim, small data) or 'diskann' (large data / >1024 dim)",
        default="ivfflat",
    )
