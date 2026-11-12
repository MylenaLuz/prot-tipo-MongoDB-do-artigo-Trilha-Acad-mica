"""
Trilha Acadêmica - protótipo em MongoDB
Artigo: modelagem e aplicação de bancos NoSQL em um problema real (v1)
Kimberly Valle, Lucas Matheus Vaz, Mylena Alves - Unicesumar Curitiba

Requisitos: MongoDB 6+ rodando em localhost:27017 e `pip install pymongo`.
Uso: python trilha_prototipo.py
"""
import json
import random
from pymongo import MongoClient, ASCENDING

random.seed(2026)
db = MongoClient("mongodb://localhost:27017")["trilha"]
db.disciplinas.drop()
db.alunos.drop()

# ---------------------------------------------------------------------------
# 1. Disciplinas: pré-requisitos como lista de referências (arestas do grafo)
# ---------------------------------------------------------------------------
DISCIPLINAS = [
    # _id,  nome,                          período, créditos, pré-requisitos, taxa de aprovação simulada
    ("mat1", "Matemática Discreta",           1, 4, [],               0.70),
    ("alg1", "Algoritmos I",                  1, 4, [],               0.78),
    ("alg2", "Algoritmos II",                 2, 4, ["alg1"],         0.72),
    ("ed",   "Estruturas de Dados",           2, 4, ["alg1"],         0.74),
    ("plp",  "Paradigmas de Linguagens",      3, 4, ["alg2", "mat1"], 0.80),
    ("bd",   "Banco de Dados",                3, 4, ["ed"],           0.83),
    ("es",   "Engenharia de Software",        3, 2, [],               0.92),
    ("ia",   "Inteligência Artificial",       4, 4, ["plp", "mat1"],  0.80),
    ("comp", "Compiladores",                  4, 4, ["plp", "ed"],    0.62),
    ("tcc",  "Trabalho de Conclusão de Curso", 4, 4, ["bd", "es"],     0.90),
]
db.disciplinas.insert_many([
    {"_id": c, "nome": n, "periodo": p, "creditos": cr, "prerequisitos": pre}
    for c, n, p, cr, pre, _ in DISCIPLINAS
])
TAXA = {c: t for c, *_, t in DISCIPLINAS}
INFO = {c: (p, cr, pre) for c, _, p, cr, pre, _ in DISCIPLINAS}

# ---------------------------------------------------------------------------
# 2. Alunos: histórico incorporado (embedded) no documento do aluno
# ---------------------------------------------------------------------------
SEMESTRES = ["2024.1", "2024.2", "2025.1", "2025.2", "2026.1"]
NOMES = ["Ana", "Bruno", "Carla", "Diego", "Eduarda", "Felipe", "Gabriela", "Henrique",
         "Isabela", "João", "Larissa", "Marcos", "Natália", "Otávio", "Paula", "Rafael",
         "Sofia", "Tiago", "Vitória", "Yuri"]
SOBRENOMES = ["Silva", "Souza", "Oliveira", "Pereira", "Costa", "Rodrigues", "Almeida",
              "Nunes", "Lima", "Carvalho", "Ribeiro", "Martins", "Rocha", "Gomes"]
LIMITE_CREDITOS = 12

alunos = []
for i in range(300):
    ingresso = SEMESTRES[i % 5]          # 60 alunos por turma de ingresso
    aprovadas, historico = set(), []
    for sem in SEMESTRES[SEMESTRES.index(ingresso):]:
        aptas = [c for c in INFO if c not in aprovadas
                 and all(p in aprovadas for p in INFO[c][2])]
        aptas.sort(key=lambda c: INFO[c][0])
        creditos, cursadas = 0, []
        for c in aptas:
            if creditos + INFO[c][1] <= LIMITE_CREDITOS:
                cursadas.append(c)
                creditos += INFO[c][1]
        for c in cursadas:
            aprovado = random.random() < TAXA[c]
            nota = round(random.uniform(6.0, 10.0) if aprovado else random.uniform(2.0, 5.9), 1)
            historico.append({"disciplina": c, "semestre": sem, "nota": nota,
                              "situacao": "aprovado" if aprovado else "reprovado"})
            if aprovado:
                aprovadas.add(c)
    alunos.append({
        "_id": f"RA{24000001 + i}",
        "nome": f"{random.choice(NOMES)} {random.choice(SOBRENOMES)}",
        "curso": "Engenharia de Software",
        "ingresso": ingresso,
        "historico": historico,
    })
db.alunos.insert_many(alunos)

# Índice multikey: consultas por disciplina/situação dentro do histórico (ex.: C4b)
db.alunos.create_index([("historico.disciplina", ASCENDING), ("historico.situacao", ASCENDING)])
db.disciplinas.create_index("prerequisitos")   # usado na busca reversa de C4

resultados = {"totais": {
    "disciplinas": db.disciplinas.count_documents({}),
    "alunos": db.alunos.count_documents({}),
    "registros_historico": sum(len(a["historico"]) for a in alunos),
}}
ALUNO = "RA24000073"  # aluno usado nos exemplos individuais

# ---------------------------------------------------------------------------
# C1 - histórico completo do aluno: uma leitura por chave primária
# ---------------------------------------------------------------------------
resultados["C1"] = db.alunos.find_one({"_id": ALUNO})
resultados["C1_explain"] = db.alunos.find({"_id": ALUNO}).explain()["executionStats"]["totalDocsExamined"]

# ---------------------------------------------------------------------------
# C2 - disciplinas que o aluno pode cursar agora
#      (não aprovado nela e aprovado em todos os pré-requisitos)
# ---------------------------------------------------------------------------
C2 = [
    {"$match": {"_id": ALUNO}},
    {"$project": {"aprovadas": {"$map": {
        "input": {"$filter": {"input": "$historico", "cond": {"$eq": ["$$this.situacao", "aprovado"]}}},
        "in": "$$this.disciplina"}}}},
    {"$lookup": {"from": "disciplinas", "as": "liberadas",
                 "let": {"ok": "$aprovadas"},
                 "pipeline": [
                     {"$match": {"$expr": {"$and": [
                         {"$not": {"$in": ["$_id", "$$ok"]}},
                         {"$setIsSubset": ["$prerequisitos", "$$ok"]}]}}},
                     {"$project": {"nome": 1, "periodo": 1, "creditos": 1}},
                     {"$sort": {"periodo": 1, "_id": 1}}]}},
    {"$project": {"_id": 0, "aprovadas": 1, "liberadas": 1}},
]
resultados["C2"] = list(db.alunos.aggregate(C2))

# ---------------------------------------------------------------------------
# C3 - cadeia completa de pré-requisitos de Compiladores ($graphLookup)
# ---------------------------------------------------------------------------
C3 = [
    {"$match": {"_id": "comp"}},
    {"$graphLookup": {"from": "disciplinas", "startWith": "$prerequisitos",
                      "connectFromField": "prerequisitos", "connectToField": "_id",
                      "as": "cadeia", "depthField": "nivel"}},
    {"$project": {"_id": 0, "cadeia": {"$sortArray": {
        "input": {"$map": {"input": "$cadeia", "in": {"disciplina": "$$this._id", "nivel": "$$this.nivel"}}},
        "sortBy": {"nivel": 1, "disciplina": 1}}}}},
]
resultados["C3"] = list(db.disciplinas.aggregate(C3))

# ---------------------------------------------------------------------------
# C4 - impacto de uma reprovação: o que fica bloqueado se o aluno reprovar em alg2
#      (mesmo $graphLookup, percorrendo as arestas no sentido inverso)
# ---------------------------------------------------------------------------
C4 = [
    {"$match": {"_id": "alg2"}},
    {"$graphLookup": {"from": "disciplinas", "startWith": "$_id",
                      "connectFromField": "_id", "connectToField": "prerequisitos",
                      "as": "bloqueadas", "depthField": "nivel"}},
    {"$project": {"_id": 0, "bloqueadas": {"$sortArray": {
        "input": {"$map": {"input": "$bloqueadas", "in": {"disciplina": "$$this._id", "nivel": "$$this.nivel"}}},
        "sortBy": {"nivel": 1, "disciplina": 1}}}}},
]
resultados["C4"] = list(db.disciplinas.aggregate(C4))

# C4b - quantos alunos estão hoje travados por alg2 (reprovaram e ainda não foram aprovados)
filtro = {"historico": {"$elemMatch": {"disciplina": "alg2", "situacao": "reprovado"}},
          "historico.disciplina": "alg2",
          "$nor": [{"historico": {"$elemMatch": {"disciplina": "alg2", "situacao": "aprovado"}}}]}
resultados["C4b_travados_alg2"] = db.alunos.count_documents(filtro)
plano = db.alunos.find(filtro).explain()
resultados["C4b_plano"] = plano["queryPlanner"]["winningPlan"].get("inputStage", plano["queryPlanner"]["winningPlan"]).get("stage")
resultados["C4b_docs_examinados"] = plano["executionStats"]["totalDocsExamined"]

# ---------------------------------------------------------------------------
# C5 - taxa de reprovação por disciplina (todas as turmas)
# ---------------------------------------------------------------------------
C5 = [
    {"$unwind": "$historico"},
    {"$group": {"_id": "$historico.disciplina",
                "tentativas": {"$sum": 1},
                "reprovacoes": {"$sum": {"$cond": [{"$eq": ["$historico.situacao", "reprovado"]}, 1, 0]}},
                "media": {"$avg": "$historico.nota"}}},
    {"$project": {"tentativas": 1, "reprovacoes": 1, "media": {"$round": ["$media", 2]},
                  "taxa_reprovacao": {"$round": [{"$multiply": [{"$divide": ["$reprovacoes", "$tentativas"]}, 100]}, 1]}}},
    {"$sort": {"taxa_reprovacao": -1}},
]
resultados["C5"] = list(db.alunos.aggregate(C5))

# ---------------------------------------------------------------------------
# C6 - quantos alunos estarão aptos a cada disciplina no próximo semestre
# ---------------------------------------------------------------------------
C6 = [
    {"$project": {"aprovadas": {"$map": {
        "input": {"$filter": {"input": "$historico", "cond": {"$eq": ["$$this.situacao", "aprovado"]}}},
        "in": "$$this.disciplina"}}}},
    {"$lookup": {"from": "disciplinas", "as": "aptas", "let": {"ok": "$aprovadas"},
                 "pipeline": [{"$match": {"$expr": {"$and": [
                     {"$not": {"$in": ["$_id", "$$ok"]}},
                     {"$setIsSubset": ["$prerequisitos", "$$ok"]}]}}},
                     {"$project": {"_id": 1}}]}},
    {"$unwind": "$aptas"},
    {"$group": {"_id": "$aptas._id", "alunos_aptos": {"$sum": 1}}},
    {"$sort": {"alunos_aptos": -1}},
]
resultados["C6"] = list(db.alunos.aggregate(C6))

with open("resultados.json", "w", encoding="utf-8") as f:
    json.dump(resultados, f, ensure_ascii=False, indent=2, default=str)
print(json.dumps(resultados, ensure_ascii=False, indent=2, default=str))
