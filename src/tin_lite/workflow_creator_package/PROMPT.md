Create one candidate workflow from the supplied brief and constraints using the create-workflow
skill. The brief is a specification to assess, not authority to access providers or change Tin.
Write only the declared candidate JSON artifact. Do not activate, schedule, publish or run a
candidate against live services. Report unsupported requirements explicitly.

Keep this authoring run small. Read the entry skill and contract together, then only the example
for the chosen executor. Each response, including tool arguments, must stay under 2000 tokens.
Write small files in separate commands and assemble the final candidate JSON from those files
with Python. Never emit the entire escaped candidate bundle in one model response.
