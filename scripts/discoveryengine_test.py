import os
from google.api_core.client_options import ClientOptions
from google.cloud import discoveryengine_v1 as discoveryengine

# ---------------------------------------------------------------------------
# Configurações (Corrigidas com base nos seus prints)
# ---------------------------------------------------------------------------
PROJECT_ID = "128281034159"
LOCATION = "us"
# ID correto do "App" (Mecanismo)
ENGINE_ID = "81ce4df1-302f-48df-96a9-b621523f5f1f-search-1762880647" 
SERVING_CONFIG_ID = "default_search"
# ID correto do "Repositório de Dados"
DATA_STORE_ID = "saipos-rag-v2_gcs_store" 
SEARCH_QUERY = "o usuario quer saber a historia da empresa"


def search_with_optimized_rag() -> discoveryengine.SearchResponse:
    """
    Executa uma busca otimizada para RAG (resumo de alta qualidade).
    """

    client_options = (
        ClientOptions(api_endpoint=f"{LOCATION}-discoveryengine.googleapis.com")
        if LOCATION != "global"
        else None
    )

    client = discoveryengine.SearchServiceClient(client_options=client_options)

    serving_config = (
        f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection"
        f"/engines/{ENGINE_ID}/servingConfigs/{SERVING_CONFIG_ID}"
    )

    data_store_path = (
        f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection"
        f"/dataStores/{DATA_STORE_ID}"
    )

    # --- INÍCIO DAS MELHORIAS ---

    snippet_spec = discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
        return_snippet=True,
        max_snippet_count=5,
    )

    summary_spec = discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
        summary_result_count=1,  # Usar 3 resultados para o resumo
        include_citations=True,
        ignore_adversarial_query=False,
        # Instrução para o modelo de resumo
        model_prompt_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec.ModelPromptSpec(
            preamble="Responda à pergunta do usuário de forma concisa e factual, baseando-se estritamente nos documentos fornecidos. Use o português do Brasil."
        )
    )

    # IMPORTANTE: Pedido de conteúdo extrativo para o RAG
    # Isto melhora drasticamente a qualidade do resumo
    extractive_content_spec = discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
        max_extractive_answer_count=1, # Queremos a "melhor" resposta
        max_extractive_segment_count=5 # Pode olhar até 5 segmentos
    )

    content_search_spec = discoveryengine.SearchRequest.ContentSearchSpec(
        snippet_spec=snippet_spec,
        summary_spec=summary_spec,
        extractive_content_spec=extractive_content_spec # <-- Adicionado
    )

    # --- FIM DAS MELHORIAS ---

    spell_correction_spec = discoveryengine.SearchRequest.SpellCorrectionSpec(
        mode=discoveryengine.SearchRequest.SpellCorrectionSpec.Mode.AUTO
    )

    data_store_spec = discoveryengine.SearchRequest.DataStoreSpec(
        data_store=data_store_path
    )

    query_expansion_spec = discoveryengine.SearchRequest.QueryExpansionSpec(
        condition=discoveryengine.SearchRequest.QueryExpansionSpec.Condition.AUTO
    )

    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=SEARCH_QUERY,
        page_size=5, # Reduzido para focar nos 5 melhores para o resumo
        language_code="pt-BR",
        content_search_spec=content_search_spec, # Spec atualizado
        spell_correction_spec=spell_correction_spec,
        data_store_specs=[data_store_spec],
        query_expansion_spec=query_expansion_spec,
    )

    print(f"Buscando (otimizado para RAG) por '{SEARCH_QUERY}' em '{DATA_STORE_ID}'...\n")
    try:
        response = client.search(request)
    except Exception as exc:
        print(f"ERRO AO EXECUTAR A BUSCA: {exc}")
        print("\n=== Análise do Erro ===")
        print(
            "Verifique se ENGINE_ID, SERVING_CONFIG_ID e DATA_STORE_ID correspondem ao "
            "que está configurado no Console do Google Cloud."
        )
        return

    print("--- Resultado Consolidado (segmentos & respostas extraídas) ---")
    extracted_passages = []
    extracted_answers = []

    # Percorre resultados para construir uma resposta manual com base nos segmentos
    for index, result in enumerate(response.results, start=1):
        print(f"--- Documento de Referência {index} ---")
        print(f"ID: {result.id}")
        document = result.document
        uri = getattr(document, "uri", None)
        if uri:
            print(f"URI: {uri}")
        segments = []
        answers = []
        derived = document.derived_struct_data or {}
        if not derived:
            print("Sem campos derivados disponíveis.")
        else:
            print("Campos derivados:")
            for key, value in derived.items():
                if key == "snippets" and value:
                    print("  - snippets:")
                    for snippet_entry in value:
                        snippet_dict = dict(snippet_entry)
                        status = snippet_dict.get("snippet_status")
                        text = snippet_dict.get("snippet")
                        print(f"      status: {status}")
                        print(f"      texto: {text}")
                elif key in {"extractive_answers", "extractive_segments"} and value:
                    print(f"  - {key}:")
                    for segment in value:
                        segment_dict = dict(segment)
                        for seg_key, seg_value in segment_dict.items():
                            print(f"      {seg_key}: {seg_value}")
                        if key == "extractive_segments":
                            segments.append(segment_dict.get("content"))
                        elif key == "extractive_answers":
                            answers.append(segment_dict.get("content"))
                else:
                    print(f"  - {key}: {value}")
        struct_data = getattr(document, "struct_data", None)
        if struct_data:
            print("Struct data (bruto):")
            for k, v in struct_data.items():
                print(f"  {k}: {v}")
        print("-----\n")

        extracted_passages.extend(filter(None, segments))
        extracted_answers.extend(filter(None, answers))

    if extracted_passages:
        print("### Passagens Relevantes ###")
        for passage in extracted_passages:
            print(f"- {passage.strip()}\n")
    if extracted_answers:
        print("### Respostas Extraídas ###")
        for answer in extracted_answers:
            print(f"- {answer.strip()}\n")

    return response


if __name__ == "__main__":
    search_with_optimized_rag()