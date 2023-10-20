import logging

import charm

import relations.database_provides
import relations.database_requires
import snap
import socket_workload
import workload

logger = logging.getLogger(__name__)

container = snap.Snap()
if connection_info := relations.database_requires.connection_info:
    workload_ = socket_workload.AuthenticatedSocketWorkload(
        container_=container, connection_info=connection_info
    )
else:
    workload_ = workload.Workload(container_=container)

if isinstance(charm.event, charm.InstallEvent):
    snap.install()
    charm.workload_version = workload_.version
elif isinstance(charm.event, charm.RemoveEvent):
    snap.uninstall()
else:
    logger.debug(
        "State of reconcile "
        f"{charm.is_leader=}, "
        f"{isinstance(workload_, workload.AuthenticatedWorkload)=}, "
        f"{workload_.container_ready=}, "
        f"{relations.database_requires.relation_breaking=}"
    )
    if charm.is_leader:
        if relations.database_requires.relation_breaking:
            relations.database_provides.delete_all_databags()
        elif isinstance(workload_, workload.AuthenticatedWorkload) and workload_.container_ready:
            relations.database_provides.reconcile_users(
                router_read_write_endpoint=f'file://{container.path("/run/mysqlrouter/mysql.sock")}',
                router_read_only_endpoint=f'file://{container.path("/run/mysqlrouter/mysqlro.sock")}',
                shell=workload_.shell,
            )
    if isinstance(workload_, workload.AuthenticatedWorkload) and workload_.container_ready:
        workload_.enable()
    elif workload_.container_ready:
        workload_.disable()
    # Set status
    if charm.is_leader:
        charm.app_status = max(
            (
                relations.database_requires.status,
                relations.database_provides.get_status(),
                charm.ActiveStatus(),
            )
        )
    charm.unit_status = max((workload_.status, charm.ActiveStatus()))
