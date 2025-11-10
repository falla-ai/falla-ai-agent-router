import logging
import os
import secrets
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import firebase_admin
from firebase_admin import firestore
from google.cloud import discoveryengine_v1alpha as discoveryengine
from google.cloud import secretmanager


class RagServiceError(Exception):
    """Erro base para o serviço de RAG."""


class RagUnauthorizedError(RagServiceError):
    """Erro para credenciais ou acesso não autorizado."""


class RagNotFoundError(RagServiceError):
    """Erro quando um recurso (tenant/playbook) não é encontrado."""


class RagConfigurationError(RagServiceError):
    """Erro quando há configuração incorreta ou ausente."""


@dataclass
class RagStoreTarget:
    """Representa um destino de busca RAG."""

    data_store_id: str
    location: str
    project_id: str
    collection_id: str


@dataclass
class RagSearchResult:
    """Resultado da consulta ao RAG."""

    summary: str
    citations: List[Dict[str, Any]]


class RagSearchService:
    """Serviço para consultas dinâmicas ao Vertex AI Search (Discovery Engine)."""

    def __init__(self) -> None:
        self.project_id = (
            os.environ.get("GCP_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("PROJECT_ID")
        )
        self.default_location = (
            os.environ.get("RAG_LOCATION")
            or os.environ.get("DISCOVERYENGINE_LOCATION")
            or "global"
        )
        self.default_project = (
            os.environ.get("RAG_PROJECT_ID")
            or self.project_id
        )
        self.default_collection = (
            os.environ.get("RAG_COLLECTION_ID")
            or "default_collection"
        )
        self._db: Optional[firestore.Client] = None
        self._secret_client: Optional[secretmanager.SecretManagerServiceClient] = None
        self._search_clients: Dict[str, discoveryengine.SearchServiceClient] = {}
        self._cached_api_key: Optional[str] = None

        if not self.project_id:
            logging.warning(
                "[RagSearchService] PROJECT_ID não está configurado. "
                "Consultas ao Secret Manager ou ao Discovery Engine podem falhar."
            )

    # -------------------------------------------------------------------------
    # Clientes (singleton)
    # -------------------------------------------------------------------------
    def _get_firestore_client(self) -> firestore.Client:
        if self._db is None:
            try:
                if not firebase_admin._apps:
                    firebase_admin.initialize_app()
                self._db = firestore.client()
                logging.info("[RagSearchService] Cliente Firestore inicializado")
            except Exception as exc:
                logging.error(
                    "[RagSearchService] Erro ao inicializar Firestore: %s", exc
                )
                raise RagConfigurationError(
                    "Não foi possível inicializar o Firestore"
                ) from exc
        return self._db

    def _get_secret_client(self) -> secretmanager.SecretManagerServiceClient:
        if self._secret_client is None:
            try:
                self._secret_client = secretmanager.SecretManagerServiceClient()
                logging.info("[RagSearchService] Cliente Secret Manager inicializado")
            except Exception as exc:
                logging.error(
                    "[RagSearchService] Erro ao inicializar Secret Manager: %s", exc
                )
                raise RagConfigurationError(
                    "Não foi possível inicializar o Secret Manager"
                ) from exc
        return self._secret_client

    def _get_search_client(
        self, project_id: str, location: str
    ) -> discoveryengine.SearchServiceClient:
        location_key = location or self.default_location
        project_key = project_id or self.default_project
        cache_key = f"{project_key}:{location_key}"
        if cache_key not in self._search_clients:
            try:
                endpoint = (
                    f"{location_key}-discoveryengine.googleapis.com"
                    if location_key != "global"
                    else "global-discoveryengine.googleapis.com"
                )
                client_options = {"api_endpoint": endpoint}
                logging.info(
                    "[RagSearchService] Inicializando cliente Discovery Engine "
                    "(cache_key=%s, endpoint=%s, project=%s, location=%s)",
                    cache_key,
                    endpoint,
                    project_key,
                    location_key,
                )
                self._search_clients[cache_key] = discoveryengine.SearchServiceClient(
                    client_options=client_options
                )
            except Exception as exc:
                logging.error(
                    "[RagSearchService] Erro ao inicializar Discovery Engine "
                    "(project=%s, location=%s): %s",
                    project_key,
                    location_key,
                    exc,
                )
                raise RagConfigurationError(
                    "Não foi possível inicializar o Discovery Engine"
                ) from exc
        return self._search_clients[cache_key]

    # -------------------------------------------------------------------------
    # Segurança (API Key)
    # -------------------------------------------------------------------------
    def _load_api_key(self) -> str:
        if self._cached_api_key:
            return self._cached_api_key

        api_key = os.environ.get("RAG_API_KEY")
        secret_name = os.environ.get("RAG_API_SECRET_NAME")

        if secret_name:
            if not self.project_id:
                raise RagConfigurationError(
                    "PROJECT_ID não definido para uso do Secret Manager"
                )
            secret_path = f"projects/{self.project_id}/secrets/{secret_name}/versions/latest"
            try:
                response = self._get_secret_client().access_secret_version(
                    request={"name": secret_path}
                )
                api_key = response.payload.data.decode("utf-8").strip()
                logging.info(
                    "[RagSearchService] API key carregada do Secret Manager (%s)",
                    secret_name,
                )
            except Exception as exc:
                logging.error(
                    "[RagSearchService] Erro ao carregar API key do Secret Manager: %s",
                    exc,
                )
                raise RagConfigurationError(
                    "Falha ao carregar a chave de API do Secret Manager"
                ) from exc

        if not api_key:
            raise RagConfigurationError(
                "Chave de API para o endpoint de RAG não está configurada"
            )

        self._cached_api_key = api_key
        return api_key

    def verify_api_key(self, provided_key: Optional[str]) -> None:
        if provided_key is None:
            logging.warning("[RagSearchService] X-Api-Key ausente")
            raise RagUnauthorizedError("Cabeçalho X-Api-Key é obrigatório")

        expected = self._load_api_key()
        if not secrets.compare_digest(provided_key.strip(), expected):
            logging.warning("[RagSearchService] X-Api-Key inválida")
            raise RagUnauthorizedError("API Key inválida")

    # -------------------------------------------------------------------------
    # Resolução de Data Store
    # -------------------------------------------------------------------------
    @staticmethod
    def _is_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "y", "on", "sim"}
        return False

    def _extract_targets_from_playbooks(
        self, playbook_configs: Dict[str, Any]
    ) -> Dict[str, RagStoreTarget]:
        targets: Dict[str, RagStoreTarget] = {}
        for playbook_name, playbook_cfg in playbook_configs.items():
            if not isinstance(playbook_cfg, dict):
                continue
            data_store_id = playbook_cfg.get("rag_datastore_id") or playbook_cfg.get(
                "rag_id"
            )
            if not data_store_id:
                continue
            location = (
                playbook_cfg.get("rag_location")
                or playbook_cfg.get("rag_region")
                or self.default_location
            )
            project_id = (
                playbook_cfg.get("rag_project_id")
                or self.default_project
            )
            collection_id = (
                playbook_cfg.get("rag_collection_id")
                or self.default_collection
            )
            logging.debug(
                "[RagSearchService] playbook target detectado "
                "(playbook=%s, project=%s, collection=%s, location=%s, data_store=%s)",
                playbook_name,
                project_id,
                collection_id,
                location,
                data_store_id,
            )
            targets[playbook_name] = RagStoreTarget(
                data_store_id=data_store_id,
                location=location,
                project_id=project_id,
                collection_id=collection_id,
            )
        return targets

    def _extract_targets_from_rag_configs(
        self, rag_configs: Dict[str, Any]
    ) -> Dict[str, RagStoreTarget]:
        targets: Dict[str, RagStoreTarget] = {}
        for alias, rag_cfg in rag_configs.items():
            if not isinstance(rag_cfg, dict):
                continue
            data_store_id = rag_cfg.get("data_store_id") or rag_cfg.get(
                "rag_datastore_id"
            )
            if not data_store_id:
                continue
            location = (
                rag_cfg.get("location")
                or rag_cfg.get("region")
                or self.default_location
            )
            project_id = (
                rag_cfg.get("project_id")
                or rag_cfg.get("rag_project_id")
                or self.default_project
            )
            collection_id = (
                rag_cfg.get("collection_id")
                or rag_cfg.get("rag_collection_id")
                or self.default_collection
            )
            logging.debug(
                "[RagSearchService] rag_config target detectado "
                "(alias=%s, project=%s, collection=%s, location=%s, data_store=%s)",
                alias,
                project_id,
                collection_id,
                location,
                data_store_id,
            )
            targets[alias] = RagStoreTarget(
                data_store_id=data_store_id,
                location=location,
                project_id=project_id,
                collection_id=collection_id,
            )
        return targets

    def resolve_store_target(
        self,
        tenant_id: str,
        playbook_name: Optional[str],
        rag_identifier: Optional[str],
        explicit_data_store_id: Optional[str],
    ) -> RagStoreTarget:
        db = self._get_firestore_client()
        tenant_doc = db.collection("tenants").document(tenant_id).get()

        if not tenant_doc.exists:
            logging.warning(
                "[RagSearchService] Tenant não encontrado: tenant_id=%s", tenant_id
            )
            raise RagNotFoundError(f"Tenant '{tenant_id}' não encontrado")

        tenant_data = tenant_doc.to_dict() or {}

        playbook_targets = self._extract_targets_from_playbooks(
            tenant_data.get("playbook_configs", {})
        )
        rag_targets = self._extract_targets_from_rag_configs(
            tenant_data.get("rag_configs", {})
        )

        allowed_targets: Dict[str, RagStoreTarget] = {}

        # Targets informados por playbooks (chave = playbook_name)
        allowed_targets.update(playbook_targets)

        # Targets adicionais mapeados por alias (chave = alias)
        allowed_targets.update(rag_targets)

        # Targets acessíveis diretamente pelo ID do data store
        for target in list(playbook_targets.values()) + list(rag_targets.values()):
            allowed_targets[target.data_store_id] = target

        if explicit_data_store_id:
            target = allowed_targets.get(explicit_data_store_id)
            if not target:
                logging.warning(
                    "[RagSearchService] Data store não autorizado. tenant_id=%s id=%s",
                    tenant_id,
                    explicit_data_store_id,
                )
                raise RagUnauthorizedError("Data store não autorizado para este tenant")
            logging.info(
                "[RagSearchService] Data store explícito autorizado. tenant=%s, "
                "project=%s, collection=%s, location=%s, data_store=%s",
                tenant_id,
                target.project_id,
                target.collection_id,
                target.location,
                target.data_store_id,
            )
            return target

        if playbook_name:
            target = playbook_targets.get(playbook_name)
            if not target:
                logging.warning(
                    "[RagSearchService] Playbook não encontrado. tenant_id=%s playbook=%s",
                    tenant_id,
                    playbook_name,
                )
                raise RagNotFoundError(
                    f"Playbook '{playbook_name}' não foi configurado para o tenant"
                )

            # Garantir que o playbook está ativo
            playbook_cfg = (tenant_data.get("playbook_configs") or {}).get(
                playbook_name
            )
            if playbook_cfg and not self._is_truthy(playbook_cfg.get("status", True)):
                logging.warning(
                    "[RagSearchService] Playbook inativo. tenant_id=%s playbook=%s",
                    tenant_id,
                    playbook_name,
                )
                raise RagConfigurationError(
                    f"Playbook '{playbook_name}' está inativo para o tenant"
                )
            logging.info(
                "[RagSearchService] Playbook target selecionado. tenant=%s, playbook=%s, "
                "project=%s, collection=%s, location=%s, data_store=%s",
                tenant_id,
                playbook_name,
                target.project_id,
                target.collection_id,
                target.location,
                target.data_store_id,
            )
            return target

        if rag_identifier:
            target = allowed_targets.get(rag_identifier)
            if not target:
                logging.warning(
                    "[RagSearchService] RAG identifier não autorizado. tenant_id=%s identifier=%s",
                    tenant_id,
                    rag_identifier,
                )
                raise RagUnauthorizedError(
                    "Identificador de RAG não autorizado para este tenant"
                )
            logging.info(
                "[RagSearchService] rag_identifier selecionado. tenant=%s, identifier=%s, "
                "project=%s, collection=%s, location=%s, data_store=%s",
                tenant_id,
                rag_identifier,
                target.project_id,
                target.collection_id,
                target.location,
                target.data_store_id,
            )
            return target

        logging.warning(
            "[RagSearchService] Nenhum identificador de data store informado"
        )
        raise RagConfigurationError(
            "Informe playbook_name, rag_identifier ou data_store_id"
        )

    # -------------------------------------------------------------------------
    # Consulta ao Discovery Engine
    # -------------------------------------------------------------------------
    def search(
        self,
        target: RagStoreTarget,
        query: str,
        summary_result_count: int = 1,
        include_citations: bool = False,
    ) -> RagSearchResult:
        if not query or not query.strip():
            raise RagConfigurationError("Query não pode ser vazia")

        summary_result_count = max(1, min(summary_result_count, 5))
        location = target.location or self.default_location
        project_id = target.project_id or self.default_project
        collection_id = target.collection_id or self.default_collection

        client = self._get_search_client(project_id, location)

        data_store_path = target.data_store_id
        if collection_id and collection_id != "default_collection":
            data_store_path = f"collections/{collection_id}/dataStores/{target.data_store_id}"

        serving_config_path = client.serving_config_path(
            project=project_id,
            location=location,
            data_store=data_store_path,
            serving_config="default_config",
        )
        logging.info(
            "[RagSearchService] Executando search (project=%s, location=%s, "
            "collection=%s, data_store=%s, serving_config=%s, query='%s', summary_count=%s, citations=%s)",
            project_id,
            location,
            collection_id,
            target.data_store_id,
            serving_config_path,
            query,
            summary_result_count,
            include_citations,
        )

        try:
            search_request = discoveryengine.SearchRequest(
                serving_config=serving_config_path,
                query=query,
                page_size=10,
                content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
                    summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
                        summary_result_count=summary_result_count,
                        include_citations=include_citations,
                        ignore_adversarial_query=True,
                    )
                ),
            )
            response = client.search(request=search_request)
        except Exception as exc:
            logging.error(
                "[RagSearchService] Erro ao consultar Discovery Engine "
                "(project=%s, location=%s, collection=%s, data_store=%s): %s",
                project_id,
                location,
                collection_id,
                target.data_store_id,
                exc,
            )
            raise RagServiceError("Falha ao consultar o mecanismo de busca") from exc

        summary_text = ""
        citations: List[Dict[str, Any]] = []

        if response.summary and response.summary.summary_text:
            summary_text = response.summary.summary_text
        else:
            summary_text = (
                "Não encontrei uma resposta direta para essa pergunta nos meus documentos."
            )

        if include_citations and response.summary and response.summary.reference_info:
            reference_info = response.summary.reference_info
            for citation in getattr(reference_info, "citations", []):
                citation_entry = {}
                anchor = getattr(citation, "anchor", None)
                uri = getattr(citation, "uri", None)
                reference = getattr(citation, "reference", None)
                if anchor:
                    citation_entry["anchor"] = anchor
                if uri:
                    citation_entry["uri"] = uri
                if reference:
                    citation_entry["reference"] = reference
                if citation_entry:
                    citations.append(citation_entry)

        logging.info(
            "[RagSearchService] Consulta concluída (tenant_target_project=%s, data_store=%s). "
            "Resumo obtido com %s caracteres e %s citações.",
            project_id,
            target.data_store_id,
            len(summary_text),
            len(citations),
        )
        return RagSearchResult(summary=summary_text, citations=citations)

    # -------------------------------------------------------------------------
    # Facade principal
    # -------------------------------------------------------------------------
    def run_query(
        self,
        *,
        tenant_id: str,
        query: str,
        playbook_name: Optional[str] = None,
        rag_identifier: Optional[str] = None,
        data_store_id: Optional[str] = None,
        summary_result_count: int = 1,
        include_citations: bool = False,
        api_key: Optional[str] = None,
    ) -> RagSearchResult:
        self.verify_api_key(api_key)
        logging.info(
            "[RagSearchService] run_query iniciado "
            "(tenant_id=%s, playbook_name=%s, rag_identifier=%s, data_store_id=%s, "
            "summary_result_count=%s, include_citations=%s, api_key_present=%s)",
            tenant_id,
            playbook_name,
            rag_identifier,
            data_store_id,
            summary_result_count,
            include_citations,
            bool(api_key),
        )

        target = self.resolve_store_target(
            tenant_id=tenant_id,
            playbook_name=playbook_name,
            rag_identifier=rag_identifier,
            explicit_data_store_id=data_store_id,
        )
        logging.info(
            "[RagSearchService] Target final selecionado "
            "(project=%s, collection=%s, location=%s, data_store=%s)",
            target.project_id,
            target.collection_id,
            target.location,
            target.data_store_id,
        )

        return self.search(
            target=target,
            query=query,
            summary_result_count=summary_result_count,
            include_citations=include_citations,
        )


