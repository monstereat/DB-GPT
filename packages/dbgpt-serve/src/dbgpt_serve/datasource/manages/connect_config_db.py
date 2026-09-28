"""DB Model for connect_config."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Union

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from dbgpt.storage.metadata import BaseDao, Model
from dbgpt_serve.datasource.api.schemas import (
    DatasourceServeRequest,
    DatasourceServeResponse,
)

logger = logging.getLogger(__name__)


class ConnectConfigEntity(Model):
    """DB connector config entity."""

    __tablename__ = "connect_config"
    id = Column(
        Integer, primary_key=True, autoincrement=True, comment="autoincrement id"
    )

    db_type = Column(String(255), nullable=False, comment="db type")
    db_name = Column(String(255), nullable=False, comment="db name")
    db_path = Column(String(255), nullable=True, comment="file db path")
    db_host = Column(String(255), nullable=True, comment="db connect host(not file db)")
    db_port = Column(String(255), nullable=True, comment="db connect port(not file db)")
    db_user = Column(String(255), nullable=True, comment="db user")
    db_pwd = Column(Text, nullable=True, comment="encrypted db password")
    comment = Column(Text, nullable=True, comment="db comment")
    sys_code = Column(String(128), index=True, nullable=True, comment="System code")
    user_id = Column(String(128), index=True, nullable=True, comment="User id")
    user_name = Column(String(128), index=True, nullable=True, comment="User name")
    gmt_created = Column(DateTime, default=datetime.now, comment="Record creation time")
    gmt_modified = Column(DateTime, default=datetime.now, comment="Record update time")
    ext_config = Column(
        Text, nullable=True, comment="Extended configuration, json format"
    )
    approval_status = Column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    submitted_by = Column(String(128), nullable=True)
    approved_by = Column(String(128), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approval_reason = Column(Text, nullable=True)
    __table_args__ = (
        UniqueConstraint("db_name", name="uk_db"),
        Index("idx_q_db_type", "db_type"),
    )


class DatasourceApprovalAuditEntity(Model):
    """Append-only record of datasource approval decisions."""

    __tablename__ = "datasource_approval_audit"
    id = Column(Integer, primary_key=True, autoincrement=True)
    db_name = Column(String(255), nullable=False, index=True)
    actor_id = Column(String(128), nullable=False)
    decision = Column(String(16), nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class ConnectConfigDao(BaseDao):
    """DB connector config dao."""

    def get_list_by_owner(
        self, actor_id: str, db_type: Optional[str] = None
    ) -> list[DatasourceServeResponse]:
        """List only datasource rows assigned to this verified submitter."""
        with self.session() as session:
            query = session.query(ConnectConfigEntity).filter(
                ConnectConfigEntity.submitted_by == actor_id
            )
            if db_type:
                query = query.filter(ConnectConfigEntity.db_type == db_type)
            return [self.to_response(item) for item in query.all()]

    def get_by_names(self, db_name: str) -> Optional[ConnectConfigEntity]:
        """Get db connect info by name."""
        session = self.get_raw_session()
        db_connect = session.query(ConnectConfigEntity)
        db_connect = db_connect.filter(ConnectConfigEntity.db_name == db_name)
        result = db_connect.first()
        session.close()
        return result

    def add_url_db(
        self,
        db_name,
        db_type,
        db_host: str,
        db_port: int,
        db_user: str,
        db_pwd: str,
        comment: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """Add db connect info.

        Args:
            db_name: db name
            db_type: db type
            db_host: db host
            db_port: db port
            db_user: db user
            db_pwd: db password
            comment: comment
        """
        try:
            session = self.get_raw_session()

            from sqlalchemy import text

            insert_statement = text(
                """
                INSERT INTO connect_config (
                    db_name, db_type, db_path, db_host, db_port, db_user, db_pwd,
                    comment, user_id, submitted_by, approval_status)
                    VALUES (:db_name, :db_type, :db_path, :db_host,
                    :db_port, :db_user, :db_pwd, :comment, :user_id,
                    :submitted_by, 'pending'
                )
            """
            )

            params = {
                "db_name": db_name,
                "db_type": db_type,
                "db_path": "",
                "db_host": db_host,
                "db_port": db_port,
                "db_user": db_user,
                "db_pwd": self._encrypt_secret(
                    db_pwd, getattr(self, "system_app", None)
                ),
                "comment": comment if comment else "",
                "user_id": user_id if user_id else "",
                "submitted_by": user_id if user_id else None,
            }
            session.execute(insert_statement, params)
            session.commit()
            session.close()
        except Exception as e:
            logger.warning("add db connect info error (%s)", type(e).__name__)

    def add_file_db(
        self,
        db_name,
        db_type,
        db_path: str,
        comment: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """Add file db connect info."""
        try:
            session = self.get_raw_session()
            insert_statement = text(
                """
                INSERT INTO connect_config(
                    db_name, db_type, db_path, db_host, db_port, db_user, db_pwd,
                    comment, user_id, submitted_by, approval_status) VALUES (
                    :db_name, :db_type, :db_path, :db_host, :db_port, :db_user, :db_pwd
                    , :comment, :user_id, :submitted_by, 'pending'
                )
            """
            )
            params = {
                "db_name": db_name,
                "db_type": db_type,
                "db_path": db_path,
                "db_host": "",
                "db_port": 0,
                "db_user": "",
                "db_pwd": "",
                "comment": comment if comment else "",
                "user_id": user_id if user_id else "",
                "submitted_by": user_id if user_id else None,
            }

            session.execute(insert_statement, params)

            session.commit()
            session.close()
        except Exception as e:
            logger.warning("add db connect info error (%s)", type(e).__name__)

    def update_db_info(
        self,
        db_name,
        db_type,
        db_path: str = "",
        db_host: str = "",
        db_port: int = 0,
        db_user: str = "",
        db_pwd: str = "",
        comment: str = "",
        ext_config: Optional[str] = None,
        updated_by: Optional[str] = None,
    ):
        """Update db connect info."""
        old_db_conf = self.get_db_config(db_name)
        if old_db_conf:
            try:
                session = self.get_raw_session()
                if not db_path:
                    update_statement = text(
                        "UPDATE connect_config SET db_type=:db_type, "
                        "db_host=:db_host, db_port=:db_port, db_user=:db_user, "
                        "db_pwd=:db_pwd, comment=:comment, submitted_by=:submitted_by, "
                        "approved_by=NULL, approved_at=NULL, approval_reason=NULL, "
                        "approval_status='pending' WHERE db_name=:db_name"
                    )
                    params = {
                        "db_type": db_type,
                        "db_host": db_host,
                        "db_port": db_port,
                        "db_user": db_user,
                        "db_pwd": (
                            self._encrypt_secret(
                                db_pwd, getattr(self, "system_app", None)
                            )
                            if db_pwd
                            else old_db_conf.get("db_pwd", "")
                        ),
                        "comment": comment,
                        "db_name": db_name,
                        "submitted_by": updated_by or old_db_conf.get("user_id"),
                    }
                else:
                    update_statement = text(
                        "UPDATE connect_config SET db_type=:db_type, "
                        "db_path=:db_path, comment=:comment, "
                        "submitted_by=:submitted_by, "
                        "approved_by=NULL, approved_at=NULL, approval_reason=NULL, "
                        "approval_status='pending' WHERE db_name=:db_name"
                    )
                    params = {
                        "db_type": db_type,
                        "db_path": db_path,
                        "comment": comment,
                        "db_name": db_name,
                        "submitted_by": updated_by or old_db_conf.get("user_id"),
                    }
                session.execute(update_statement, params)
                session.commit()
                session.close()
            except Exception as e:
                logger.warning("edit db connect info error (%s)", type(e).__name__)
            return True
        raise ValueError(f"{db_name} not have config info!")

    def get_db_config(self, db_name):
        """Return db connect info by name."""
        session = self.get_raw_session()
        try:
            if not db_name:
                raise ValueError("Database name cannot be empty")

            select_statement = text(
                """
                SELECT
                    *
                FROM
                    connect_config
                WHERE
                    db_name = :db_name
            """
            )
            params = {"db_name": db_name}
            result = session.execute(select_statement, params)

            fields = [field[0] for field in result.cursor.description]

            row = result.cursor.fetchone()
            if not row:
                logger.error(f"No database config found for db_name: {db_name}")
                raise ValueError(f"Database config not found for: {db_name}")

            return {fields[i]: row[i] for i in range(len(fields))}
        finally:
            session.close()

    @staticmethod
    def _encrypt_secret(value: Optional[str], system_app=None) -> Optional[str]:
        if not value:
            return value
        from dbgpt_serve.datasource.security import encrypt_secret

        return encrypt_secret(value, system_app)

    def require_approved(self, db_name: str) -> Dict[str, Any]:
        config = self.get_db_config(db_name)
        if config.get("approval_status") != "approved":
            raise PermissionError("Datasource is not approved")
        return config

    def review(
        self,
        db_name: str,
        actor_id: str,
        decision: str,
        reason: str = "",
        allow_submitter_approval: bool = False,
    ):
        if decision not in {"approve", "reject"}:
            raise ValueError("Unsupported datasource approval decision")
        session = self.get_raw_session()
        try:
            with session.begin():
                row = (
                    session.execute(
                        text(
                            "SELECT approval_status, submitted_by FROM connect_config "
                            "WHERE db_name=:db_name"
                        ),
                        {"db_name": db_name},
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise ValueError("Datasource not found")
                if row["approval_status"] != "pending":
                    raise ValueError("Datasource is not pending review")
                if (
                    decision == "approve"
                    and row["submitted_by"] == actor_id
                    and not allow_submitter_approval
                ):
                    raise PermissionError("Datasource submitter cannot approve it")
                approved_by = actor_id if decision == "approve" else None
                approved_at = datetime.now() if decision == "approve" else None
                session.execute(
                    text(
                        "UPDATE connect_config SET approval_status=:status, "
                        "approved_by=:approved_by, approved_at=:approved_at, "
                        "approval_reason=:reason WHERE db_name=:db_name"
                    ),
                    {
                        "status": "approved" if decision == "approve" else "rejected",
                        "approved_by": approved_by,
                        "approved_at": approved_at,
                        "reason": reason,
                        "db_name": db_name,
                    },
                )
                session.execute(
                    text(
                        "INSERT INTO datasource_approval_audit "
                        "(db_name, actor_id, decision, reason, created_at) "
                        "VALUES (:db_name, :actor_id, :decision, :reason, :created_at)"
                    ),
                    {
                        "db_name": db_name,
                        "actor_id": actor_id,
                        "decision": decision,
                        "reason": reason,
                        "created_at": datetime.now(),
                    },
                )
        finally:
            session.close()
        return self.get_db_config(db_name)

    def transfer_owner(
        self, db_name: str, actor_id: str, owner_id: str, reason: str = ""
    ):
        """Transfer datasource ownership and record the change atomically."""
        owner_id = owner_id.strip()
        if not owner_id:
            raise ValueError("Datasource owner is required")
        session = self.get_raw_session()
        try:
            with session.begin():
                row = (
                    session.execute(
                        text(
                            "SELECT submitted_by, user_id FROM connect_config "
                            "WHERE db_name=:db_name"
                        ),
                        {"db_name": db_name},
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise ValueError("Datasource not found")
                previous_owner = row["submitted_by"] or row["user_id"] or None
                if previous_owner == owner_id:
                    raise ValueError("Datasource already belongs to this owner")
                audit_reason = json.dumps(
                    {
                        "from_owner_id": previous_owner,
                        "to_owner_id": owner_id,
                        "reason": reason,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                session.execute(
                    text(
                        "UPDATE connect_config SET submitted_by=:owner_id, "
                        "user_id=:owner_id, approval_status='pending', "
                        "approved_by=NULL, approved_at=NULL, approval_reason=NULL "
                        "WHERE db_name=:db_name"
                    ),
                    {"owner_id": owner_id, "db_name": db_name},
                )
                session.execute(
                    text(
                        "INSERT INTO datasource_approval_audit "
                        "(db_name, actor_id, decision, reason, created_at) "
                        "VALUES (:db_name, :actor_id, 'transfer', :reason, :created_at)"
                    ),
                    {
                        "db_name": db_name,
                        "actor_id": actor_id,
                        "reason": audit_reason,
                        "created_at": datetime.now(),
                    },
                )
        finally:
            session.close()
        return self.get_db_config(db_name)

    def list_pending(self):
        session = self.get_raw_session()
        try:
            result = session.execute(
                text(
                    "SELECT db_name, db_type, user_id, submitted_by, comment, "
                    "approval_status FROM connect_config "
                    "WHERE approval_status='pending' ORDER BY db_name"
                )
            )
            return [dict(row) for row in result.mappings().all()]
        finally:
            session.close()

    def list_approval_audit(self, db_name: str):
        session = self.get_raw_session()
        try:
            result = session.execute(
                text(
                    "SELECT db_name, actor_id, decision, reason, created_at "
                    "FROM datasource_approval_audit WHERE db_name=:db_name "
                    "ORDER BY id"
                ),
                {"db_name": db_name},
            )
            return [dict(row) for row in result.mappings().all()]
        finally:
            session.close()

    def get_db_list(self, db_name: Optional[str] = None, user_id: Optional[str] = None):
        """Get db list."""
        session = self.get_raw_session()
        statement = "SELECT * FROM connect_config"
        conditions = []
        params = {}
        if user_id:
            conditions.append("(user_id = :user_id OR user_id = '' OR user_id IS NULL)")
            params["user_id"] = user_id
        if db_name:
            conditions.append("db_name = :db_name")
            params["db_name"] = db_name
        if conditions:
            statement += " WHERE " + " AND ".join(conditions)

        try:
            result = session.execute(text(statement), params)
            fields = [field[0] for field in result.cursor.description]  # type: ignore
            data = []
            for row in result.cursor.fetchall():  # type: ignore
                row_dict = {}
                for i, field in enumerate(fields):
                    row_dict[field] = row[i]
                data.append(row_dict)
            return data
        finally:
            session.close()

    def delete_db(self, db_name):
        """Delete db connect info."""
        session = self.get_raw_session()
        delete_statement = text("""DELETE FROM connect_config where db_name=:db_name""")
        params = {"db_name": db_name}
        session.execute(delete_statement, params)
        session.commit()
        session.close()
        return True

    def from_request(
        self, request: Union[DatasourceServeRequest, Dict[str, Any]]
    ) -> ConnectConfigEntity:
        """Convert the request to an entity.

        Args:
            request (Union[ServeRequest, Dict[str, Any]]): The request

        Returns:
            T: The entity
        """
        request_dict = (
            request.dict() if isinstance(request, DatasourceServeRequest) else request
        )
        ext_config = request_dict.get("ext_config")
        if ext_config and isinstance(ext_config, dict):
            request_dict["ext_config"] = json.dumps(ext_config, ensure_ascii=False)
        entity = ConnectConfigEntity(**request_dict)
        return entity

    def to_request(self, entity: ConnectConfigEntity) -> DatasourceServeRequest:
        """Convert the entity to a request.

        Args:
            entity (T): The entity

        Returns:
            REQ: The request
        """
        ext_config = entity.ext_config
        if ext_config:
            ext_config = json.loads(ext_config)
        return DatasourceServeRequest(
            id=entity.id,
            db_type=entity.db_type,
            db_name=entity.db_name,
            db_path=entity.db_path,
            db_host=entity.db_host,
            db_port=entity.db_port,
            db_user=entity.db_user,
            db_pwd=entity.db_pwd,
            comment=entity.comment,
            ext_config=ext_config,
        )

    def to_response(self, entity: ConnectConfigEntity) -> DatasourceServeResponse:
        """Convert the entity to a response.

        Args:
            entity (T): The entity

        Returns:
            REQ: The request
        """
        ext_config = entity.ext_config
        if ext_config:
            ext_config = json.loads(ext_config)
        gmt_created = (
            entity.gmt_created.strftime("%Y-%m-%d %H:%M:%S")
            if entity.gmt_created
            else None
        )
        gmt_modified = (
            entity.gmt_modified.strftime("%Y-%m-%d %H:%M:%S")
            if entity.gmt_modified
            else None
        )
        return DatasourceServeResponse(
            id=entity.id,
            db_type=entity.db_type,
            db_name=entity.db_name,
            db_path=entity.db_path,
            db_host=entity.db_host,
            db_port=entity.db_port,
            db_user=entity.db_user,
            db_pwd=entity.db_pwd,
            comment=entity.comment,
            ext_config=ext_config,
            gmt_created=gmt_created,
            gmt_modified=gmt_modified,
            approval_status=entity.approval_status,
            submitted_by=entity.submitted_by,
            approved_by=entity.approved_by,
            approved_at=(
                entity.approved_at.strftime("%Y-%m-%d %H:%M:%S")
                if entity.approved_at
                else None
            ),
            approval_reason=entity.approval_reason,
        )
