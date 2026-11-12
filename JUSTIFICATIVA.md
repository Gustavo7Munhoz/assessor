# Justificativa

1. **1.Quais arquivos você criou ou modificou? Indique o caminho de cada um.** 
criei app/tools/perfil.py, app/routes/perfil.py e JUSTIFICATIVA.md
modifiquei app/schemas.py, app/vectorstore.py, app/main.py, app/tools/financeiro.py, app/graph.py e app/prompts.py.

2. **2.Por onde o perfil entra, e onde cada parte dele é gravada?** 
o perfil entra pelo 'POST /perfil', os campos estruturados vão para 'perfis_financeiros' no MongoDB; 'preferencias' vira embedding em 'perfil_preferencias`' no Qdrant.

3. **3.Como o as preferencias são guardadas e consultadas, e por que não é busca por palavra?** 
o texto é indexado com embeddings Gemini, e o sistema procura textos com sentido parecido, usando também o 'user_id'. Buscar por palavra não encontra restrições expressas com vocabulário diferente, como associar cripto a “nada agressivo”.

4. **4.Você criou uma tool ou duas? Por quê?** 
criei uma tool, 'consultar_perfil_financeiro', porque uma consulta retorna os campos estruturados e a preferência mais relacionada à pergunta no mesmo contexto do especialista.

5. **5.O que garante que o perfil de um usuário não apareceria para outro, se houvesse mais de um?** 
O 'user_id' vem do contexto da requisição, é usado no filtro do Mongo e no filtro obrigatório do Qdrant, o modelo não o preenche na tool.

6. **6.Sua tool consulta o banco diretamente ou faz uma chamada HTTP na própria API? Por quê?** ela consulta Mongo e Qdrant diretamente, usando o acesso que o sistema já tem ao banco. Assim evita chamada HTTP para a própria aplicação e mantém o contexto do usuário fora do controle do modelo.

7. **7.Por que não existe um agente "perfil"?** 
não existe agente “perfil” porque perfil é dado de apoio do especialista financeiro, e não é independente.

8. **8.	Por que o chat não altera o cadastro?** 
a única operação exposta ao chat é leitura. A escrita ocorre apenas no 'POST /perfil', então pedidos de mudança não persistem cadastro.


Retirei o .venv para conseguir zipar e enviar