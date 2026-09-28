from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from dbgpt.component import SystemApp
from dbgpt_ext.rag.chunk_manager import ChunkParameters
from dbgpt_serve.core.tests.conftest import (  # noqa: F401
    asystem_app,
    client,
    config,
    system_app,
)
from dbgpt_serve.rag.api.endpoints import space_retrieve
from dbgpt_serve.rag.retriever import knowledge_space

from ..api.schemas import (
    DocumentServeRequest,
    DocumentServeResponse,
    KnowledgeRetrieveRequest,
    KnowledgeSyncRequest,
    SpaceServeResponse,
)
from ..models.chunk_db import DocumentChunkDao
from ..models.document_db import KnowledgeDocumentDao
from ..models.models import KnowledgeSpaceDao, SpaceServeRequest
from ..service.service import Service


@pytest.fixture
def mock_system_app():
    return Mock()


@pytest.fixture
def mock_dao():
    return AsyncMock(KnowledgeSpaceDao)


@pytest.fixture
def mock_document_dao():
    return AsyncMock(KnowledgeDocumentDao)


@pytest.fixture
def mock_chunk_dao():
    return AsyncMock(DocumentChunkDao)


@pytest.fixture
def service(system_app: SystemApp, mock_dao, mock_document_dao, mock_chunk_dao, config):
    return Service(
        system_app=system_app,
        config=config,
        dao=mock_dao,
        document_dao=mock_document_dao,
        chunk_dao=mock_chunk_dao,
    )


@pytest.mark.asyncio
async def test_create_space(service):
    request = SpaceServeRequest(name="Test2Space")

    service.get = Mock(return_value=None)
    service._dao.create_knowledge_space = Mock(
        return_value={"id": "1", "name": "TestSpace"}
    )

    response = service.create_space(request)

    assert response["name"] == "TestSpace"
    service._dao.create_knowledge_space.assert_called_once_with(request)


@pytest.mark.parametrize(
    "setting_name",
    ["DBGPT_DAILY_TOKEN_LIMIT", "DBGPT_REACT_DAILY_TOKEN_LIMIT"],
)
@pytest.mark.asyncio
async def test_knowledge_graph_sync_fails_closed_before_dispatch(
    service, monkeypatch, setting_name
):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv(setting_name, "1000")
    doc = SimpleNamespace(id=1, doc_name="test", space="graph-space", status="TODO")
    service._document_dao.documents_by_ids = Mock(return_value=[doc])
    service.get = Mock(
        return_value=SimpleNamespace(vector_type="KnowledgeGraph", context=None)
    )
    service._sync_knowledge_document = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await service.sync_document(
            [
                KnowledgeSyncRequest(
                    doc_id=1,
                    space_id="1",
                    chunk_parameters=ChunkParameters(chunk_strategy="CHUNK_BY_SIZE"),
                )
            ]
        )

    assert exc_info.value.status_code == 503
    service._sync_knowledge_document.assert_not_awaited()


@pytest.mark.parametrize(
    "setting_name",
    ["DBGPT_DAILY_TOKEN_LIMIT", "DBGPT_REACT_DAILY_TOKEN_LIMIT"],
)
@pytest.mark.asyncio
async def test_vector_store_sync_remains_available_with_daily_quota(
    service, monkeypatch, setting_name
):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv(setting_name, "1000")
    doc = SimpleNamespace(id=1, doc_name="test", space="vector-space", status="TODO")
    service._document_dao.documents_by_ids = Mock(return_value=[doc])
    service.get = Mock(return_value=SimpleNamespace(vector_type="VectorStore"))
    service._sync_knowledge_document = AsyncMock()

    result = await service.sync_document(
        [
            KnowledgeSyncRequest(
                doc_id=1,
                space_id="1",
                chunk_parameters=ChunkParameters(chunk_strategy="CHUNK_BY_SIZE"),
            )
        ]
    )

    assert result == [1]
    service._sync_knowledge_document.assert_awaited_once()


@pytest.mark.parametrize(
    "setting_name",
    ["DBGPT_DAILY_TOKEN_LIMIT", "DBGPT_REACT_DAILY_TOKEN_LIMIT"],
)
@pytest.mark.asyncio
async def test_llm_backed_retrieval_fails_closed_when_quota_enabled(
    monkeypatch, setting_name
):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv(setting_name, "1000")
    space = SimpleNamespace(
        vector_type="VectorStore",
        context='{"embedding":{"retrieve_mode":"Tree"}}',
    )

    class FakeService:
        called = False

        def get(self, request):
            return space

        async def retrieve(self, request, resolved_space):
            self.called = True
            return []

    service = FakeService()
    with pytest.raises(HTTPException) as exc_info:
        await space_retrieve(
            1, KnowledgeRetrieveRequest(space_id=1, query="test"), service
        )

    assert exc_info.value.status_code == 503
    assert service.called is False


@pytest.mark.asyncio
async def test_semantic_retrieval_remains_available_when_quota_enabled(monkeypatch):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "1000")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "")
    space = SimpleNamespace(vector_type="VectorStore", context=None)

    class FakeService:
        called = False

        def get(self, request):
            return space

        async def retrieve(self, request, resolved_space):
            self.called = True
            return []

    service = FakeService()
    await space_retrieve(1, KnowledgeRetrieveRequest(space_id=1, query="test"), service)

    assert service.called is True


def test_knowledge_retriever_requires_metered_client_when_quota_enabled(
    monkeypatch,
):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "1000")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "")
    raw_client = object()
    wrapped_client = object()
    mock_system = Mock()
    mock_system.get_component.return_value.create.return_value = object()
    monkeypatch.setattr(
        knowledge_space, "DefaultLLMClient", lambda *_args, **_kwargs: raw_client
    )
    retriever = object.__new__(knowledge_space.KnowledgeSpaceRetriever)
    retriever._system_app = mock_system

    with pytest.raises(RuntimeError, match="metered knowledge retrieval"):
        _ = retriever.llm_client

    from dbgpt.core.interface.operators.llm_operator import (
        scoped_llm_client_wrapper,
    )

    with scoped_llm_client_wrapper(lambda _client: wrapped_client):
        assert retriever.llm_client is wrapped_client


def test_create_space_already_exists(service):
    request = SpaceServeRequest(name="ExistingSpace")
    existing_space = {"id": "1", "name": "ExistingSpace"}

    service.get = Mock(return_value=existing_space)  # Simulate existing space

    with pytest.raises(HTTPException) as excinfo:
        service.create_space(request)

    assert excinfo.value.status_code == 400
    assert "have already named" in excinfo.value.detail


def test_update_space(service):
    request = SpaceServeRequest(id="1", name="UpdatedSpace")
    existing_space = [SpaceServeRequest(name="ExistingSpace")]

    service._dao.get_knowledge_space = Mock(return_value=existing_space)
    service._dao.update_knowledge_space = Mock(return_value=request)

    response = service.update_space(request)

    assert response.name == "UpdatedSpace"
    service._dao.update_knowledge_space.assert_called_once()


def test_update_space_not_found(service):
    request = SpaceServeRequest(id="1", name="NonExistentSpace")
    service._dao.get_knowledge_space = Mock(return_value=[])

    with pytest.raises(HTTPException) as excinfo:
        service.update_space(request)

    assert excinfo.value.status_code == 400
    assert "no space name named" in excinfo.value.detail


@pytest.mark.asyncio
async def test_create_document(service):
    request = DocumentServeRequest(
        space_id="1", doc_name="TestDocument", doc_type="DOCUMENT"
    )

    service.get = Mock(return_value=SpaceServeResponse(id=1, name="TestSpace"))
    service._document_dao.get_knowledge_documents = Mock(return_value=[])
    service._document_dao.create_knowledge_document = Mock(return_value="2")

    response = service.create_document(request)
    assert response == "2"


@pytest.mark.asyncio
async def test_delete_document(service):
    document_id = 2
    existing_document = DocumentServeResponse(
        id=document_id, space="TestSpace", vector_ids=None
    )

    service._document_dao.get_one = Mock(return_value=existing_document)
    service._dao.get_knowledge_space = Mock(
        return_value=[SpaceServeRequest(id="1", name="TestSpace")]
    )
    service._chunk_dao.raw_delete = Mock()
    service._document_dao.raw_delete = Mock(return_value=existing_document)

    response = service.delete_document(document_id)

    assert response.id == document_id
    service._chunk_dao.raw_delete.assert_called_once_with(document_id)
    service._document_dao.raw_delete.assert_called_once_with(existing_document)


# @pytest.mark.asyncio
# async def test_batch_document_sync_success(service):
#     space_id = "test_space_id"
#     chunk_parameters=ChunkParameters(chunk_strategy="CHUNK_BY_SIZE")
#     sync_request = KnowledgeSyncRequest(doc_id=1,
#                                         chunk_parameters=chunk_parameters)
#
#     # Mocking document retrieval
#     doc_mock = MagicMock()
#     doc_mock.status = SyncStatus.TODO.name  # Mock an initial status
#     doc_mock.id = 1
#     doc_mock.doc_name = "Test Document"
#
#     service._document_dao.documents_by_ids.return_value = [
#         doc_mock]  # Mocking the response
#
#     # Setting mock for chunk strategies
#     sync_request.chunk_parameters.chunk_strategy = "CHUNK_BY_SIZE"
#
#     # Run the test asynchronously
#     doc_ids = await service._batch_document_sync(space_id, [sync_request])
#
#     service._sync_knowledge_document.assert_awaited_once_with(
#         space_id,
#         doc_mock,
#         sync_request.chunk_parameters
#     )
