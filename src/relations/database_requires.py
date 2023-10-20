# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation to MySQL charm"""

import logging
import typing

import charm

logger = logging.getLogger(__name__)


class _IncompleteDatabag(KeyError):
    """Databag is missing required key"""


class _MissingRelation(Exception):
    """Relation to MySQL charm does (or will) not exist for this unit

    If this unit is tearing down, the relation could still exist for other units.
    """

    def __init__(self) -> None:
        super().__init__(charm.BlockedStatus(f"Missing relation: {_ENDPOINT_NAME}"))


class _RelationBreaking(_MissingRelation):
    """Relation to MySQL charm will be broken for this unit after the current event is handled

    Relation currently exists

    If this unit is tearing down, the relation could still exist for other units.
    """


class ConnectionInformation:
    """Information for connection to MySQL cluster

    User has permission to:
    - Create databases & users
    - Grant all privileges on a database to a user
    (Different from user that MySQL Router runs with after bootstrap.)
    """

    def __init__(self) -> None:
        relations = charm.endpoints[_ENDPOINT_NAME]
        if not relations:
            raise _MissingRelation()
        assert len(relations) == 1
        relation = relations[0]
        assert isinstance(relation, charm.RemoteRelation)
        if charm.is_leader:
            # Database name disregarded by MySQL charm if "mysqlrouter" extra user role requested
            relation.my_app["database"] = "mysql_innodb_cluster_metadata"
            relation.my_app["extra-user-roles"] = "mysqlrouter"
        if relation.breaking:
            # Relation will be broken after the current event is handledop
            raise _RelationBreaking()
        try:
            endpoints = relation.remote_app["endpoints"].split(",")
            assert len(endpoints) == 1
            endpoint = endpoints[0]
            self.host: str = endpoint.split(":")[0]
            self.port: str = endpoint.split(":")[1]
            self.username: str = relation.remote_app["username"]
            self.password: str = relation.remote_app["password"]
        except KeyError:
            raise _IncompleteDatabag(
                charm.WaitingStatus(
                    f"Waiting for {relation._remote_app_name} app on {_ENDPOINT_NAME} endpoint"
                )
            )


_ENDPOINT_NAME = "backend-database"

connection_info: typing.Optional[ConnectionInformation] = None
"""Information for connection to MySQL cluster"""

relation_breaking = False
"""Whether relation will be broken after the current event is handled"""

status: typing.Optional[charm.Status] = None
"""Non-active status"""

try:
    connection_info = ConnectionInformation()
except (_MissingRelation, _IncompleteDatabag) as e:
    if isinstance(e, _RelationBreaking):
        relation_breaking = True
    status = e.args[0]
