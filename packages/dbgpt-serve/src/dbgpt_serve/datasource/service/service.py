import json
import logging
from dataclasses import fields
from typing import List, Optional, Union

from fastapi import HTTPException

from dbgpt._private.config import Config
from dbgpt._private.pydantic import model_to_dict
from dbgpt.component import ComponentType, SystemApp
from dbgpt.core.awel.dag.dag_manager import DAGManager
from dbgpt.datasource.parameter import BaseDatasourceParameters
from dbgpt.storage.metadata import BaseDao
from dbgpt.util.executor_utils import ExecutorFactory
from dbgpt_ext.datasource.schema import DBType
from dbgpt_serve.core import BaseService, ResourceTypes
from dbgpt_serve.datasource.manages import ConnectorManager
from dbgpt_serve.datasource.manages.connect_config_db import (
    ConnectConfigDao,
    ConnectConfigEntity,
)
from dbgpt_serve.datasource.security import protect_persisted_state

from ...rag.storage_manager import StorageManager
from ..api.schemas import (
    DatasourceCreateRequest,
    DatasourceQueryResponse,
    DatasourceServeRequest,
    DatasourceServeResponse,
)
from ..config import SERVE_SERVICE_COMPONENT_NAME, ServeConfig

logger = logging.getLogger(__name__)
CFG = Config()


def _private_parameter_names(parameter) -> set[str]:
    return {
        item.name
        for item in fields(parameter)
        if "privacy" in str(item.metadata.get("tags", "")).split(",")
    }


class Service(
    BaseService[ConnectConfigEntity, DatasourceServeRequest, DatasourceServeResponse]
):
    """The service class for Flow"""

    name = SERVE_SERVICE_COMPONENT_NAME

    def __init__(
        self,
        system_app: SystemApp,
        config: ServeConfig,
        dao: Optional[ConnectConfigDao] = None,
    ):
        self._system_app = system_app
        self._dao: ConnectConfigDao = dao
        self._dag_manager: Optional[DAGManager] = None
        self._db_summary_client = None
        self._serve_config = config

        super().__init__(system_app)

    def init_app(self, system_app: SystemApp) -> None:
        """Initialize the service

        Args:
            system_app (SystemApp): The system app
        """
        super().init_app(system_app)

        self._dao = self._dao or ConnectConfigDao()
        self._system_app = system_app

    def before_start(self):
        """Execute before the application starts"""
        from dbgpt_serve.datasource.service.db_summary_client import DBSummaryClient

        super().before_start()
        self._db_summary_client = DBSummaryClient(self._system_app)

    def after_start(self):
        """Execute after the application starts"""

    @property
    def dao(
        self,
    ) -> BaseDao[ConnectConfigEntity, DatasourceServeRequest, DatasourceServeResponse]:
        """Returns the internal DAO."""
        return self._dao

    @property
    def config(self) -> ServeConfig:
        """Returns the internal ServeConfig."""
        return self._serve_config

    @property
    def datasource_manager(self) -> ConnectorManager:
        if not self._system_app:
            raise ValueError("SYSTEM_APP is not set")
        return ConnectorManager.get_instance(self._system_app)

    @property
    def storage_manager(self) -> StorageManager:
        if not self._system_app:
            raise ValueError("SYSTEM_APP is not set")
        return StorageManager.get_instance(self._system_app)

    def create(
        self,
        request: Union[DatasourceCreateRequest, DatasourceServeRequest],
        *,
        actor_id: Optional[str] = None,
    ) -> DatasourceQueryResponse:
        """Create a new Datasource entity

        Args:
            request (Union[DatasourceCreateRequest, DatasourceServeRequest]): The
                request to create a new Datasource entity. DatasourceServeRequest is
                deprecated.

        Returns:
            DatasourceQueryResponse: The response
        """
        str_db_type = (
            request.type
            if isinstance(request, DatasourceCreateRequest)
            else request.db_type
        )
        desc = ""
        if isinstance(request, DatasourceCreateRequest):
            connector_params: BaseDatasourceParameters = (
                self.datasource_manager._create_parameters(request)
            )
            persisted_state = connector_params.persisted_state()
            desc = request.description
        else:
            persisted_state = model_to_dict(request)
            desc = request.comment
        if "ext_config" in persisted_state and isinstance(
            persisted_state["ext_config"], dict
        ):
            persisted_state["ext_config"] = json.dumps(
                persisted_state["ext_config"], ensure_ascii=False
            )
        param_cls = self.datasource_manager._get_param_cls(str_db_type)
        parameter = (
            connector_params
            if isinstance(request, DatasourceCreateRequest)
            else param_cls.from_persisted_state(persisted_state)
        )
        persisted_state = protect_persisted_state(
            persisted_state, parameter, self._system_app
        )
        persisted_state["id"] = None
        persisted_state["user_id"] = actor_id or ""
        persisted_state["submitted_by"] = actor_id
        persisted_state["approval_status"] = "pending"
        persisted_state["comment"] = desc
        db_name = persisted_state.get("db_name")
        datasource = self._dao.get_by_names(db_name)
        if datasource:
            raise HTTPException(
                status_code=400,
                detail=f"datasource name:{db_name} already exists",
            )
        try:
            db_type = DBType.of_db_type(str_db_type)
            if not db_type:
                raise HTTPException(
                    status_code=400, detail=f"Unsupported Db Type, {str_db_type}"
                )

            res = self._dao.create(persisted_state)

        except Exception as e:
            logger.error("Add datasource failed (%s)", type(e).__name__)
            raise ValueError("Add db connect info error!") from None
        return self._to_query_response(res)

    def update(
        self,
        request: Union[DatasourceCreateRequest, DatasourceServeRequest],
        *,
        actor_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> DatasourceQueryResponse:
        """Create a new Datasource entity

        Args:
            request (Union[DatasourceCreateRequest, DatasourceServeRequest]): The
                request to create a new Datasource entity. DatasourceServeRequest is
                deprecated.

        Returns:
            DatasourceQueryResponse: The response
        """
        desc = ""
        if isinstance(request, DatasourceCreateRequest):
            param_cls = self.datasource_manager._get_param_cls(request.type)
            mapping = param_cls._persisted_state_mapping()
            database_field = next(
                (name for name, column in mapping.items() if column == "db_name"),
                "db_name",
            )
            existing = self._dao.get_by_names(request.params.get(database_field))
            if existing:
                self._authorize_datasource(existing, actor_id, is_admin)
            params = dict(request.params)
            if existing:
                stored_state = model_to_dict(existing)
                if isinstance(stored_state.get("ext_config"), str):
                    try:
                        stored_state["ext_config"] = json.loads(
                            stored_state["ext_config"]
                        )
                    except json.JSONDecodeError:
                        stored_state["ext_config"] = {}
                current = param_cls.from_persisted_state(stored_state)
                for name in _private_parameter_names(current):
                    if not params.get(name):
                        params[name] = getattr(current, name, "")
                request.params = params
            connector_params: BaseDatasourceParameters = (
                self.datasource_manager._create_parameters(request)
            )
            persisted_state = connector_params.persisted_state()
            desc = request.description
        else:
            existing = self._dao.get_by_names(request.db_name)
            if existing:
                self._authorize_datasource(existing, actor_id, is_admin)
                if not request.db_pwd:
                    request.db_pwd = existing.db_pwd or ""
                current_ext = existing.ext_config
                if isinstance(current_ext, str) and current_ext:
                    try:
                        current_ext = json.loads(current_ext)
                    except json.JSONDecodeError:
                        current_ext = {}
                request_ext = request.ext_config or {}
                if isinstance(current_ext, dict):
                    param_cls = self.datasource_manager._get_param_cls(request.db_type)
                    for name in _private_parameter_names(param_cls):
                        if not request_ext.get(name) and current_ext.get(name):
                            request_ext[name] = current_ext[name]
                request.ext_config = request_ext
            persisted_state = model_to_dict(request)
            desc = request.comment
        if "ext_config" in persisted_state and isinstance(
            persisted_state["ext_config"], dict
        ):
            persisted_state["ext_config"] = json.dumps(
                persisted_state["ext_config"], ensure_ascii=False
            )
        db_type = (
            request.type
            if isinstance(request, DatasourceCreateRequest)
            else request.db_type
        )
        param_cls = self.datasource_manager._get_param_cls(db_type)
        parameter = (
            connector_params
            if isinstance(request, DatasourceCreateRequest)
            else param_cls.from_persisted_state(persisted_state)
        )
        persisted_state = protect_persisted_state(
            persisted_state, parameter, self._system_app
        )
        if existing:
            persisted_state["id"] = existing.id
            persisted_state["user_id"] = (
                getattr(existing, "user_id", None) or existing.submitted_by or ""
            )
            persisted_state["submitted_by"] = existing.submitted_by
        persisted_state["comment"] = desc
        persisted_state["approval_status"] = "pending"
        persisted_state["approved_by"] = None
        persisted_state["approved_at"] = None
        persisted_state["approval_reason"] = None
        db_name = persisted_state.get("db_name")
        if not db_name:
            raise HTTPException(status_code=400, detail="datasource name is required")
        datasources = self._dao.get_by_names(db_name)
        if datasources is None:
            raise HTTPException(status_code=404, detail="datasource not found")
        res = self._dao.update({"id": datasources.id}, persisted_state)
        # Connection params (host/user/pwd/ext_config/...) may have just
        # changed; drop any cached connector so the next get_connector
        # reflects the new config.
        self.datasource_manager.invalidate_connector(db_name)
        return self._to_query_response(res)

    def get(
        self,
        datasource_id: str,
        *,
        actor_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> Optional[DatasourceQueryResponse]:
        """Get a Flow entity

        Args:
            request (DatasourceServeRequest): The request

        Returns:
            DatasourceServeResponse: The response
        """
        res = self._dao.get_one({"id": datasource_id})
        if not res:
            raise HTTPException(status_code=404, detail="datasource not found")
        self._authorize_datasource(res, actor_id, is_admin)
        return self._to_query_response(res)

    def delete(
        self,
        datasource_id: str,
        *,
        actor_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> Optional[DatasourceServeResponse]:
        """Delete a Flow entity

        Args:
            datasource_id (str): The datasource_id

        Returns:
            DatasourceServeResponse: The data after deletion
        """
        db_config = self._dao.get_one({"id": datasource_id})
        if not db_config:
            raise HTTPException(status_code=404, detail="datasource not found")
        self._authorize_datasource(db_config, actor_id, is_admin)
        self._db_summary_client.delete_db_profile(db_config.db_name)
        self._dao.delete({"id": datasource_id})
        # Datasource is gone; drop the cached connector so we don't
        # hand callers a connector pointing at a config row that no
        # longer exists.
        self.datasource_manager.invalidate_connector(db_config.db_name)
        return db_config

    def get_list(
        self,
        db_type: Optional[str] = None,
        *,
        actor_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> List[DatasourceQueryResponse]:
        """List the Flow entities.

        Returns:
            List[DatasourceServeResponse]: The list of responses
        """
        if is_admin:
            query_request = {"db_type": db_type} if db_type else {}
            query_list = self.dao.get_list(query_request)
        else:
            if not actor_id:
                raise HTTPException(
                    status_code=401, detail="Datasource identity required"
                )
            query_list = self.dao.get_list_by_owner(actor_id, db_type=db_type)
        results = []
        for item in query_list:
            results.append(self._to_query_response(item))
        return results

    def _to_query_response(
        self, res: DatasourceServeResponse
    ) -> DatasourceQueryResponse:
        param_cls = self.datasource_manager._get_param_cls(res.db_type)
        param = param_cls.from_persisted_state(model_to_dict(res))
        param_dict = param.to_dict()
        for name in _private_parameter_names(param):
            if name in param_dict:
                param_dict[name] = ""
        return DatasourceQueryResponse(
            type=res.db_type,
            params=param_dict,
            description=res.comment,
            id=res.id,
            db_name=res.db_name,
            gmt_created=res.gmt_created,
            gmt_modified=res.gmt_modified,
            approval_status=res.approval_status,
            submitted_by=res.submitted_by,
            approved_by=res.approved_by,
            approved_at=res.approved_at,
            approval_reason=res.approval_reason,
        )

    def datasource_types(self) -> ResourceTypes:
        """List the datasource types.

        Returns:
            List[str]: The list of datasource types
        """
        return self.datasource_manager.get_supported_types()

    def test_connection(self, request: DatasourceCreateRequest) -> bool:
        """Test the connection of the datasource.

        Args:
            request (DatasourceServeRequest): The request

        Returns:
            bool: The test result
        """
        return self.datasource_manager.test_connection(request)

    def refresh(
        self,
        datasource_id: str,
        *,
        actor_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> bool:
        """Refresh the datasource.

        Args:
            datasource_id (str): The datasource_id

        Returns:
            bool: The refresh result
        """
        db_config = self._dao.get_one({"id": datasource_id})
        if not db_config:
            raise HTTPException(status_code=404, detail="datasource not found")
        self._authorize_datasource(db_config, actor_id, is_admin)
        self.datasource_manager.storage.require_approved(db_config.db_name)

        self._db_summary_client.delete_db_profile(db_config.db_name)
        # The cached connector's reflected MetaData may be stale relative
        # to whatever caused the refresh; force a rebuild on next access.
        self.datasource_manager.invalidate_connector(db_config.db_name)

        # async embedding
        executor = self._system_app.get_component(
            ComponentType.EXECUTOR_DEFAULT, ExecutorFactory
        ).create()  # type: ignore
        executor.submit(
            self._db_summary_client.db_summary_embedding,
            db_config.db_name,
            db_config.db_type,
        )
        return True

    @staticmethod
    def _authorize_datasource(
        datasource,
        actor_id: Optional[str],
        is_admin: bool,
    ) -> None:
        """Hide resources from non-owners and keep unowned legacy rows admin-only."""
        if is_admin:
            return
        if actor_id and getattr(datasource, "submitted_by", None) == actor_id:
            return
        raise HTTPException(status_code=404, detail="datasource not found")
