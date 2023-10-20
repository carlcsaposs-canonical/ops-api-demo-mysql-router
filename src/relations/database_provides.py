# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Relation(s) to one or more application charms"""

import logging
import typing

import charm

import mysql_shell

logger = logging.getLogger(__name__)


class _IncompleteDatabag(KeyError):
    """Databag is missing required key"""


class _RelationBreaking(Exception):
    """Relation will be broken for this unit after the current event is handled

    If this unit is tearing down, the relation could still exist for other units.
    """


class _UnsupportedExtraUserRole(Exception):
    """Application charm requested unsupported extra user role"""


class _Relation(charm.RemoteRelation):
    """Relation to one application charm"""

    def _get_username(self, database_requires_username: str) -> str:
        """Database username"""
        # Prefix username with username from database requires relation.
        # This ensures a unique username if MySQL Router is deployed in a different Juju model
        # from MySQL.
        # (Relation IDs are only unique within a Juju model.)
        return f"{database_requires_username}-{self.id}"


class _RelationThatRequestedUser(_Relation):
    """Related application charm that has requested a database & user"""

    def __init__(self, relation: charm.RemoteRelation) -> None:
        super().__init__(relation)
        if self.breaking:
            raise _RelationBreaking
        try:
            self._database = self.remote_app["database"]
        except KeyError:
            raise _IncompleteDatabag(
                charm.WaitingStatus(
                    f"Waiting for {self._remote_app_name} app on {_ENDPOINT_NAME} endpoint"
                )
            )
        if self.remote_app.get("extra-user-roles"):
            raise _UnsupportedExtraUserRole(
                f"{self._remote_app_name} app requested unsupported extra user role on {_ENDPOINT_NAME} endpoint"
            )

    def create_database_and_user(
        self,
        *,
        router_read_write_endpoint: str,
        router_read_only_endpoint: str,
        shell: mysql_shell.Shell,
    ) -> None:
        """Create database & user and update databag."""
        username = self._get_username(shell.username)
        password = shell.create_application_database_and_user(
            username=username, database=self._database
        )
        logger.debug(
            f"Setting databag {self.id=} {self._database=}, {username=}, {router_read_write_endpoint=}, {router_read_only_endpoint=}"
        )
        self.my_app["database"] = self._database
        self.my_app["username"] = username
        self.my_app["password"] = password
        self.my_app["endpoints"] = router_read_write_endpoint
        self.my_app["read-only-endpoints"] = router_read_only_endpoint
        logger.debug(
            f"Set databag {self.id=} {self._database=}, {username=}, {router_read_write_endpoint=}, {router_read_only_endpoint=}"
        )


class _UserNotCreated(Exception):
    """Database & user has not been provided to related application charm"""


class _RelationWithCreatedUser(_Relation):
    """Related application charm that has been provided with a database & user"""

    def __init__(self, relation: charm.RemoteRelation) -> None:
        super().__init__(relation)
        for key in ("database", "username", "password", "endpoints", "read-only-endpoints"):
            if key not in self.my_app:
                raise _UserNotCreated

    def delete_databag(self) -> None:
        """Remove connection information from databag."""
        logger.debug(f"Deleting databag {self.id=}")
        self.my_app.clear()
        logger.debug(f"Deleted databag {self.id=}")

    def delete_user(self, *, shell: mysql_shell.Shell) -> None:
        """Delete user and update databag."""
        self.delete_databag()
        shell.delete_user(self._get_username(shell.username))


def _created_users() -> typing.List[_RelationWithCreatedUser]:
    created_users = []
    for relation in charm.endpoints[_ENDPOINT_NAME]:
        try:
            created_users.append(_RelationWithCreatedUser(relation))
        except _UserNotCreated:
            pass
    return created_users


def reconcile_users(
    *, router_read_write_endpoint: str, router_read_only_endpoint: str, shell: mysql_shell.Shell
) -> None:
    """Create requested users and delete inactive users.

    When the relation to the MySQL charm is broken, the MySQL charm will delete all users
    created by this charm. Therefore, this charm does not need to delete users when that
    relation is broken.
    """
    logger.debug(f"Reconciling users {router_read_write_endpoint=}, {router_read_only_endpoint=}")
    requested_users = []
    for relation in charm.endpoints[_ENDPOINT_NAME]:
        try:
            requested_users.append(_RelationThatRequestedUser(relation))
        except (_RelationBreaking, _IncompleteDatabag, _UnsupportedExtraUserRole):
            pass
    logger.debug(f"State of reconcile users {requested_users=}, {_created_users()=}")
    for relation in requested_users:
        if relation not in _created_users():
            relation.create_database_and_user(
                router_read_write_endpoint=router_read_write_endpoint,
                router_read_only_endpoint=router_read_only_endpoint,
                shell=shell,
            )
    for relation in _created_users():
        if relation not in requested_users:
            relation.delete_user(shell=shell)
    logger.debug(f"Reconciled users {router_read_write_endpoint=}, {router_read_only_endpoint=}")


def delete_all_databags() -> None:
    """Remove connection information from all databags.

    Called when relation with MySQL is breaking

    When the MySQL relation is re-established, it could be a different MySQL cluster—new users
    will need to be created.
    """
    logger.debug("Deleting all application databags")
    for relation in _created_users():
        # MySQL charm will delete user; just delete databag
        relation.delete_databag()
    logger.debug("Deleted all application databags")


def get_status() -> typing.Optional[charm.Status]:
    """Report non-active status."""
    requested_users = []
    exception_reporting_priority = (_UnsupportedExtraUserRole, _IncompleteDatabag)
    exceptions: typing.List[Exception] = []
    for relation in charm.endpoints[_ENDPOINT_NAME]:
        try:
            requested_users.append(_RelationThatRequestedUser(relation))
        except _RelationBreaking:
            pass
        except exception_reporting_priority as exception:
            exceptions.append(exception)
    for exception_type in exception_reporting_priority:
        for exception in exceptions:
            if isinstance(exception, exception_type):
                return exception.args[0]
    if not requested_users:
        return charm.BlockedStatus(f"Missing relation: {_ENDPOINT_NAME}")


_ENDPOINT_NAME = "database"
