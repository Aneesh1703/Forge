"""
index_repository(path)

↓

create repository

↓

walk repository

↓

batch files

↓

for each batch

    begin transaction

    parse every file

    collect RepositoryFiles

    collect CodeSymbols

    bulk save files

    bulk save symbols

    commit

↓

update repository statistics

↓

return repository id
"""
