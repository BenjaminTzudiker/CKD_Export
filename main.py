import psycopg2
import sys
from progress.bar import Bar
from collections import deque

# Default sentinel value for function default checking
default = object()

# Contains the Table instances used to store export information. tableInfo[0] contains the primary table. Order matters in some cases - child tables should always come after their parents!
tableInfo = []

#
# Run.py functions
#

def run(mode = "buffered", filename = "export.csv", buffer = 10000):
    """
    Attempts to run the export using the inforamtion given in tableInfo.
    
    Keyword Arguments:
    mode -- Tells the script how to behave, string (default "temptable")
        "slow" - Performs many small queries. Likely to be noticeably slower than any of the other options, but uses minimal memory and requires no table creation priveleges.
        "localjoin" - Queries whole tables and joins/builds the export before writing the file. Uses a lot more memory than "slow", but it should take less time and still requires no table creation priveleges.
        "buffered" - Creates export-specific sorted temporary tables in the database instead of joining in python, then queries portions of those. Requires temporary table creation priveleges.
    filename -- String value that denotes the name of the file the export will write to, string (default "export.csv")
    buffer -- Defines the size of each table's buffer for the \"buffered\" mode with no effect on other modes, int (default 10000)
    """
    print("Starting export with mode \"{m}\"...".format(m = mode))
    
    if mode == "buffered":
        
        print("Setting up temporary tables...")
        for table in tableInfo:
            createJoinedTemporaryTable(table, tableInfo[0])
        
        print("Counting maximum entries for secondary tables...")
        bar = Bar("Tables        ", max = len(tableInfo) - 1)
        for i in range(1, len(tableInfo)):
            if not tableInfo[i].forceOneToOne:
                bar.next()
                runQuery("select max(a.c) from (select count(z.{c}) as c from {t} as z group by {c}) as a".format(c = "export_primary", t = temporaryTableName(table)))
                tableInfo[i].maxEntries = cursor.fetchall()[0][0]
        for i in range(1, len(tableInfo)):
            if tableInfo[i].forceOneToOne:
                bar.next()
                tableInfo[i].maxEntries = tableInfo[i].parentTable.maxEntries
        bar.finish()
        
        with open(filename, "w+") as file:
            
            print("Writing columns...")
            writeColumnHeaders(file)
            
            print("Writing entries...")
            bufferList = {table:Buffer(table, buffer) for table in tableInfo}
            nextEntry = {table:next(bufferList[table]) for table in tableInfo}
            runQuery("select count(*) from {t}".format(t = temporaryTableName(tableInfo[0])))
            bar = LargerDequeBar("Rows          ", max = cursor.fetchall()[0][0], suffix = "%(index)d/%(max)d - ETA: %(eta_td)s - Elapsed: %(elapsed_td)s        ")
            
            while not nextEntry[tableInfo[0]] == None:
                
                bar.next()
                primaryKey = nextEntry[tableInfo[0]][0]
                
                for table in tableInfo:
                    
                    entryCount = 0
                    
                    while not nextEntry[table] == None and nextEntry[table][0] == primaryKey:
                        
                        entryCount += 1
                        
                        for i in range(1, len(nextEntry[table])):
                            
                            file.write(str(nextEntry[table][i]) + ",")
                            
                        nextEntry[table] = next(bufferList[table])
                        
                    file.write("," * ((table.maxEntries - entryCount) * len([column for column in table.columns if column.include == 2])))
                    
                file.seek(file.tell() - 1)
                file.write("\n")
                
            bar.finish()
            
            print("Export to file {f} completed, exiting.".format(f = filename))
            
    else:
        print("Counting maximum entries for each table...")
        updateMaxEntries()
        print("Querying primary table keys...")
        primaryKeys = queryPrimaryKeys()
        if mode == "localjoin":
            """with open(filename, "w+") as file:
                print("Writing columns...")
                writeColumnHeaders(file)
                print("Creating dictionaries...")
                exportWidth = 0
                for table in tableInfo:
                    exportWidth += table.maxEntries * (len(table.columns) - (0 if table.displayKeyColumn else 1))
                exportData = {key:[None for j in range(exportWidth)] for key in primaryKeys}
                keyDict = {table.parentTable:dict() for table in tableInfo if not (table.parentTable == None or table.parentTable == tableInfo[0])}
                tableDataStartingIndex = 0
                print("Querying tables...")
                barQuery = Bar("Tables Queried", max = len(tableInfo))
                for table in tableInfo:
                    barQuery.next()
                    tableData = {key:tableDataStartingIndex for key in exportData.keys()}
                    tableDataStartingIndex += table.maxEntries * len(table.columns)
                    keyColumnIndex = table.columns.index(table.keyColumn)
                    if table == tableInfo[0]:
                        entryData = entryTableExportData(mode, table, None)
                    elif table.parentTable == tableInfo[0]:
                        entryData = entryTableExportData(mode, table, primaryKeys)
                    else:
                        entryData = entryTableExportData(mode, table, keyDict[table.parentTable].keys())
                    for 
                    if table in keyDict.keys():
                        pass"""
        elif mode == "slow":
            with open("export.csv", "w+") as file:
                print("Writing columns...")
                writeColumnHeaders(file)
                print("Writing entries...")
                bar = Bar("Row", max = len(primaryKeys))
                for primaryKey in primaryKeys:
                    bar.next()
                    for table in tableInfo:
                        tableData = entryTableExportData(mode, table, primaryKey)
                        for entryData in tableData:
                            for data in entryData:
                                file.write(str(data) + ",")
                        file.write("," * ((table.maxEntries - len(tableData)) * len(tableData[0])))
                    file.seek(file.tell() - 1)
                    file.write("\n")
                bar.finish()

def setupAddPrimaryTable(tableName, columnNames = default, keyColumnName = default, displayKeyColumn = True, whereInclude = "", whereMarkers = []):
    """
    Stores the export settings for the primary table.
    
    Keyword arguments:
    tableName -- The name of the table, string
    columnNames -- The names of the columns that should be imported, string[] (default all column names in table)
    keyColumnName -- The name of the unique column used as the primary key for the table, string (default columnNames[0])
    displayKeyColumn -- If false, this will prevent the export from writing the table's key column, boolean (default True)
    whereInclude -- Optionally the statement in a where query used to limit the rows that are expored, string (default "")
    whereMarkers -- Optionally adds new columns that contain either one or zero for each row based on a where clause provided, list of tuples (default [])
    """
    if columnNames == default:
        columnNames = [col[0] for col in getAllColumnNamesFromTableName(tableName)]
    if keyColumnName == default:
        keyColumnName = columnNames[0]
        
    print("Setting up primary table {t}...".format(t = tableName))
    columns = [Column(col[0], col[0], col[1], 2 if col[0] in columnNames else 1 if col[0] == keyColumnName else 0) for col in getAllColumnNamesFromTableName(tableName)]
    keyColumn = getColumnFromName(keyColumnName, columns)
    for marker in whereMarkers:
        columns.append(Column("(case when " + marker[1] + " then 1 else 0 end) as " + marker[0], marker[0], "integer"))
    table = Table(tableName, columns, keyColumn)
    table.displayKeyColumn = displayKeyColumn
    table.whereInclude = whereInclude
    table.whereMarkers = whereMarkers
    
    if len(tableInfo) == 0:
        tableInfo.append(table)
    else:
        tableInfo[0] = table
    
    print("Primary table {t} added.".format(t = tableName))
    return table

def setupAddSecondaryTable(tableName, columnNames = default, keyColumnName = default, parentTableName = default, parentKeyColumnName = default, displayKeyColumn = True, forceOneToOne = False, orderBy = [], limit = 0):
    """
    Stores the export settings for a table with a one-to-one relationship to the parent table.
    
    Keyword arguments:
    tableName -- The name of the table, string
    columnNames -- The names of the columns that should be imported, string[] (default all column names in table)
    keyColumnName -- The name of the column used to reference the parent table, string (default columnNames[0])
    parentTableName -- The name of the table that the key links to, string (default primary table name)
    parentKeyColumnName -- The name of the column in the parent table that contains the foreign keys, string (default keyColumnName)
    displayKeyColumn -- If false, this will prevent the export from writing the table's key column, boolean (default True)
    forceOneToOne -- If trie, this will set the maximum number of entries to be that of its parent table, boolean (default False)
    orderBy -- Optionally provides additional ordering instructions, list of tuples (default [])
    limit -- Limits the number of entries included for a specific parent key where 0 is no limit, integer (default 0)
    """
    if columnNames == default:
        columnNames = [col[0] for col in getAllColumnNamesFromTableName(tableName)]
    if keyColumnName == default:
        keyColumnName = columnNames[0]
    if parentTableName == default:
        parentTableName = tableInfo[0].table.name
    if parentKeyColumnName == default:
        parentKeyColumnName = keyColumnName
    
    print("Setting up table {t}...".format(t = tableName))
    if not tableInfo[0] == None:
        
        columns = [Column(col[0], col[0], col[1], 2 if col[0] in columnNames else 1 if col[0] == keyColumnName else 0) for col in getAllColumnNamesFromTableName(tableName)]
        keyColumn = getColumnFromName(keyColumnName, columns)
        parentTable = getTableFromName(parentTableName)
        parentKeyColumn = getColumnFromName(parentKeyColumnName, parentTable.columns)
        if parentKeyColumn.include == 0:
            parentKeyColumn.include == 1
        table = Table(tableName, columns, keyColumn, parentTable, parentKeyColumn)
        table.displayKeyColumn = displayKeyColumn
        table.forceOneToOne = forceOneToOne
        table.orderBy = orderBy
        table.limit = limit
        
        tableInfo.append(table)
        
        print("Table {t} added.".format(t = tableName))
        return table
    else:
        raise NoPrimaryTableException()
        return None

#
# Classes and generators
#

class Column:
    """
    Stores information about a column that is needed to export it.
    
    name -- The SQL name of the column, string (default "")
    displayName -- The name used in the exported CSV file, string (default name)
    type -- The SQL column type, string (default "variable character")
    include -- The extent to which the column should be included with 0 = not included, 1 = included in temp table but not exported, 2 = included and exported, int (default 2)
    """
    def __init__(self, n = "", dispn = default, t = "variable character", inc = 2):
        if dispn == default:
            dispn = n
        self.name = n
        self.displayName = dispn
        self.type = t
        self.include = inc

class Table:
    """
    Stores information about a table that is needed to export it.
    """
    def __init__(self, n = "", col = [], key = None, ref = None, refKey = None):
        self.name = n
        self.columns = col
        self.keyColumn = key
        self.parentTable = ref
        self.parentKeyColumn = refKey
        self.displayKeyColumn = True
        self.maxEntries = 1
        self.orderBy = []
        self.whereInclude = None
        self.whereMarkers = []
        self.forceOneToOne = False
        self.limit = 0

class LargerDequeBar(Bar):
        def __init__(self, *args, **kwargs):
            super(LargerDequeBar, self).__init__(*args, **kwargs)
            self._xput = deque(maxlen = 2000)
        def update_avg(self, n, dt):
            if n > 0:
                self._xput.append(dt / n)
                self.avg = sum(self._xput) / len(self._xput)

def Buffer(table, size):
    """
    Generator function that returns the next entry to write and queries the database to refill the buffer when needed
    """
    buffer = queryNextBuffer(table, size, 0)
    index = 0
    offset = size
    while True:
        if index < len(buffer):
            index += 1
            yield buffer[index - 1]
        else:
            index = 0
            buffer = queryNextBuffer(table, size, offset)
            if len(buffer) > 0 and not buffer == None:
                yield buffer[index]
                offset += size
            else:
                break
    yield None
            

#
# Database functions
#

def connect(dbuser, dbpass, dbname, dbhost):
    """
    Attempts to connect to the database.
    
    Accepts the username and password along with the host and database name (all as strings). Returns the cursor object if the connection succeeds, or attempts to exit the script (and returns None) if an exception is thrown.
    """
    try:
        global conn
        conn = psycopg2.connect("dbname='{name}' user='{user}' host='{host}' password='{password}'".format(user = dbuser, password = dbpass, name = dbname, host = dbhost))
        global cursor
        cursor = conn.cursor()
        return cursor
    except:
        print("Database connection failed, check database information specified in run.py python file.")
        print("Exiting...")
        sys.exit()
        return None

def close():
    """
    Attempts to close the connection to the database.
    """
    try:
        global cursor
        cursor.close()
        global conn
        conn.close()
    except:
        print("Failed to close database connection.")

def runQuery(query):
    """
    Tries to run the query passed to the function.
    
    Accepts a string as the sql query (sans semicolon). Returns true if the query execution does not throw an exception, or false if an exception is thrown.
    """
    try:
        cursor.execute("{q}".format(q = query))
        return True
    except Exception as e:
        print("\nQuery execution failed for query:\n" + query + "\n" + str(e))
        return False

#
# Setup helper functions
#

def getTableFromName(name, collection = tableInfo):
    """
    Searches the collection for a table with the specified name.
    
    Accepts the name of the table as a string, optionally with a specific collection to search (defaults to tableInfo). Returns the first table object found with that name, or None if a table with that name isn't found.
    """
    for table in collection:
        if table.name == name:
            return table
    else:
        print("No table with name " + name + " found.")
        return None

def getColumnFromName(name, collection):
    """
    Searches the collection for a column with the specified name.
    
    Accepts the name of the column as a string and the collection to search. Returns the first column object found with that name, or None if a column with that name isn't found.
    """
    for column in collection:
        if column.name == name:
            return column
    else:
        return None

def countKeyColumnAlias(count = 0):
    """
    Returns an SQL table alias as a string for a given integer.
    """
    return "z" * (count + 1)

def entryTableExportData(mode, table, key):
    """
    Returns a list containing the entries for a table to be written to the exported csv file.
    
    Accepts the exported table as a table object and the primary key in the primary table. Returns a list of tuples (one tuple for each matching entry) if the query succeeds, or None if the query fails.
    """
    if mode == "localjoin":
        success = runQuery(entryTableExportDataLocaljoinQueryConstructor(table, key))
    elif mode == "slow":
        success = runQuery(entryTableExportDataSlowQueryConstructor(table, key))
    if success:
        return cursor.fetchall()
    else:
        return None

def entryTableExportDataLocaljoinQueryConstructor(table, keys):
    if keys == None or table == tableInfo[0]:
        return "select t1.{c} from {t} as t1{q}".format(c = ", ".join(column.name for column in table.columns), t = table.name, q = " {w".format(w = table.whereInclude) if not (table.whereInclude == "" or table.whereInclude == None) else "")
    else:
        return "select t1.{c} from {t} as t1 where exists (select 1 from values(({keys})) as t2 where t2.column1 = t1.{key})".format(c = ", ".join(column.name for column in table.columns), t = table.name, key = table.keyColumn.name, keys = "), (".join(keys))

def entryTableExportDataSlowQueryConstructor(table, primaryKey, count = 0):
    """
    Recursive helper function used to construct the query for entryTableExportData.
    """
    if count == 0:
        columns = table.columns
        if not table.displayKeyColumn:
            try:
                columns.remove(table.keyColumn)
            except:
                print("Key column {c} not found in table {t}.".format(c = table.keyColumn.name, t = table.name))
        return "select {c} from {t} as {ta} where {q}".format(t = table.name, c = ", ".join(countKeyColumnAlias() + "." + column.name for column in columns), ta = countKeyColumnAlias(), q = entryTableExportDataSlowQueryConstructor(table, primaryKey, count + 1))
    elif (table == tableInfo[0] or table.parentTable == None):
        return "{ta}.{c} = {value}".format(ta = countKeyColumnAlias(count - 1), c = table.keyColumn.name, value = "{quotes}{v}{quotes}".format(v = primaryKey, quotes = '"' if table.keyColumn.type == "variable character" else ""))
    else:
        return "exists(select 1 from {ref} as {refa} where {ta}.{c} = {refa}.{refc} and {q})".format(ref = table.parentTable.name, refa = countKeyColumnAlias(count), ta = countKeyColumnAlias(count - 1), c = table.keyColumn.name, refc = table.parentKeyColumn.name, q = entryTableExportDataSlowQueryConstructor(table.parentTable, primaryKey, count + 1))

def countMaxEntriesWithKeyColumn(table):
    """
    Counts the maximum number of rows that link to the same key in the primary table.
    
    Accepts the table as a table object. Returns the number of lines as an int if the query succeeds, or zero if the query fails.
    """
    success = runQuery(countMaxEntriesWithKeyColumnQueryConstructor(table))
    if success:
        return int(cursor.fetchone()[0])
    else:
        return 0

def countMaxEntriesWithKeyColumnQueryConstructor(table, originalTable = default, count = 0):
    """
    Helper function used to construct the query for countMaxEntriesWithKeyColumn.
    """
    if originalTable == default:
        originalTable = table
    if count == 0:
        return "select max({outera}.c) from (select count({ta}.{c}) as c from {t} as {ta}".format(t = table.name, c = table.keyColumn.name, ta = countKeyColumnAlias(count + 1), outera = countKeyColumnAlias()) + countMaxEntriesWithKeyColumnQueryConstructor(table, originalTable, count + 1)
    elif (table == tableInfo[0] or table.parentTable == None):
        return " group by {ta}.{c}) as {outera}".format(ta = countKeyColumnAlias(count), c = table.keyColumn.name, origta = countKeyColumnAlias(count + 1), origc = originalTable.keyColumn.name, outera = countKeyColumnAlias())
    else:
        return "{w} inner join {ref} as {refa} on {ta}.{c} = {refa}.{refc}".format(w = " where {q}".format(q = table.whereInclude) if not (table.whereInclude == "" or table.whereInclude == None) else "", ref = table.parentTable.name, c = table.keyColumn.name, refc = table.parentKeyColumn.name, refa = countKeyColumnAlias(count + 1), ta = countKeyColumnAlias(count)) + countMaxEntriesWithKeyColumnQueryConstructor(table.parentTable, originalTable, count + 1)

def getAllColumnNamesFromTableName(tableName):
    """
    Returns a tuble containing all the column names and data types in a table.
    
    Accepts the table name as a string. Returns a tuple with one tuple entry per column (each containing the name and data type as strings), or an empty tuple if the query fails.
    """
    success = runQuery("select column_name, data_type from information_schema.columns where table_name = '{t}'".format(t = tableName))
    if success:
        return cursor.fetchall()
    else:
        return tuple()

#
# Run function helper methods
#

def createJoinedTemporaryTable(table = default, primaryTable = default):
    """
    Creates a sorted temporary table for a database table that is used to speed up the export process.
    
    Takes the table that you want to make a temp table for and the primary table as table objects, both of which default to the first entry in the tableInfo list.
    """
    if table == default:
        table = tableInfo[0]
    if primaryTable == default:
        primaryTable = tableInfo[0]
    
    print("Creating temporary table for{primary} table {table}...".format(primary = " primary" if table == tableInfo[0] else "", table = table.name))
    if table == primaryTable or table.parentTable == None:
        success = createPrimaryJoinedTemporaryTable(table)
        
        if success:
            print("Adding unique identifier column...")
            success = runQuery("alter table {table} add column export_id serial primary key".format(table = temporaryTableName(table)))
            
        else:
            print("Error creating primary key column for temporary table {t}.".format(t = temporaryTableName(table)))
            
    else:
        success = createSecondaryJoinedTemporaryTable(table, primaryTable)
    
    if success:
        print("Creating index on export primary key...")
        
        query = "create index {index} on {table} (export_primary asc nulls last{order})"
        query = query.format(index = temporaryTableName(table) + "_primary_index",
                    table = temporaryTableName(table),
                    order = (", " + ", ".join(order[0] + " " + ("asc" if order[1] == True else "desc") for order in table.orderBy)) if not (table.orderBy == None or len(table.orderBy) == 0) else "")
        
        success = runQuery(query)
        
        if success:
            print("Analyzing temp table...")
            runQuery("analyze {t}".format(t = temporaryTableName(table)))
            conn.commit()
            return True
        
        else:
            print("Error creating indexes for temporary table {t}.".format(t = temporaryTableName(table)))
            return None
        
    else:
        print("Error creating temporary table {t}.".format(t = temporaryTableName(table)))
        return None

def createPrimaryJoinedTemporaryTable(table = default):
    """
    Sets up and then loads data into a new temporary table used later in the export process.
    
    Loads the primary table with a single query, filtering out/adding marker columns for included where statements. Takes the primary table as a table object, defaulting to the first table in the tableInfo list.
    """
    if table == default:
        table = tableInfo[0]
    
    query = "select {tableAlias}.{primaryKeyColumn} as export_primary, {columns} into temporary table {tempTable} from {table} as {tableAlias}{whereInclude} order by export_primary asc{order}"
    query = query.format(tableAlias = countKeyColumnAlias(), 
                 primaryKeyColumn = table.keyColumn.name, 
                 columns = ", ".join((countKeyColumnAlias() + "." if column.name in getAllColumnNamesFromTableName(table) else "") + column.name.format(alias = countKeyColumnAlias() + ".") for column in table.columns if column.include > 0), 
                 tempTable = temporaryTableName(table), 
                 table = table.name, 
                 whereInclude = " where " + table.whereInclude.format(alias = countKeyColumnAlias() + ".") if not (table.whereInclude == "" or table.whereInclude == None) else "", 
                 order = (", " + ", ".join(order[0] + " " + ("asc" if order[1] == True else "desc") for order in table.orderBy)) if not (table.orderBy == None or len(table.orderBy) == 0) else "", 
                 alias = countKeyColumnAlias() + ".")
    
    return runQuery(query)

def createSecondaryJoinedTemporaryTable(table, primaryTable = default, fetchSize = 10000):
    """
    Sets up and then loads data into a new temporary table used later in the export process.
    
    Builds the table and runs one query for each parent key, keeping track of progress and limiting entries/ordering as needed. Takes the secondary table to load and the primary table as table objects, defaulting the primary table to the first table in the tableInfo list. Also takes the cursor fetch size as an int, defaulting to 10000.
    """
    if primaryTable == default:
        primaryTable = tableInfo[0]
    success = True
    
    print("Setting up table structure...")
    
    query = "select {parentTableAlias}.export_primary, {columns} into temporary table {tempTable} from {table} as {tableAlias} cross join {parentTable} as {parentTableAlias} limit 0"
    query = query.format(parentTableAlias = countKeyColumnAlias(0), 
                 columns = ", ".join(countKeyColumnAlias(1) + "." + column.name for column in table.columns if column.include > 0), 
                 tempTable = temporaryTableName(table), 
                 table = table.name, 
                 tableAlias = countKeyColumnAlias(1), 
                 parentTable = temporaryTableName(table.parentTable))
    
    success = runQuery(query) and success
    
    print("Adding unique identifier column...")
    
    query = "alter table {tempTable} add column export_id serial primary key"
    query = query.format(tempTable = temporaryTableName(table))
    
    success = runQuery(query) and success
    
    print("Counting keys...")
    
    query = "select count(*) from {table}"
    query = query.format(table = temporaryTableName(table.parentTable))
    
    success = runQuery(query)
    maxlen = cursor.fetchall()[0][0]
    
    print("Declaring cursor...")
    
    query = "declare cursor_export_keys_{table} cursor for select distinct export_primary, {columns} from {table} order by export_primary asc"
    query = query.format(table = temporaryTableName(table.parentTable), 
                 columns = table.parentKeyColumn.name)
    
    success = runQuery(query) and success
    
    print("Fetching initial entries from cursor...")
    
    query = "fetch forward {size} from cursor_export_keys_{table}"
    query = query.format(size = fetchSize, 
                 table = temporaryTableName(table.parentTable))
    
    success = runQuery(query) and success
    keys = cursor.fetchall()
    
    print("Filling table...")
    bar = LargerDequeBar("Parent Entries", max = maxlen, suffix = "%(index)d/%(max)d - ETA: %(eta_td)s - Elapsed: %(elapsed_td)s        ")
    
    while not len(keys) == 0:
        for key in keys:
            if not success:
                print("Previous query execution failed, halting...")
                break
            bar.next()
            
            query = "insert into {tempTable} (export_primary, {columns}) select {primaryKeyValue}, {columns} from {table} where {keyColumn} = {keyValue}{order}{limit}"
            query = query.format(tempTable = temporaryTableName(table), 
                         columns = ", ".join(column.name for column in table.columns if column.include > 0), 
                         primaryKeyValue = key[0], 
                         table = table.name, 
                         keyColumn = table.parentKeyColumn.name, 
                         keyValue = "{quotes}{key}{quotes}".format(key = key[1], quotes = '"' if table.parentKeyColumn.type == "variable character" else ""), 
                         order = (" order by " + ", ".join(order[0] + " " + ("asc" if order[1] == True else "desc") for order in table.orderBy)) if not (table.orderBy == None or len(table.orderBy) == 0) else "", 
                         limit = " limit " + str(table.limit) if table.limit > 0 else "")
            
            success = runQuery(query) and success
            
        query = "fetch forward {size} from cursor_export_keys_{table}"
        query = query.format(size = fetchSize, 
                     table = temporaryTableName(table.parentTable))
        
        success = runQuery(query) and success
        keys = cursor.fetchall()
        
    bar.finish()
    return success

"""def createJoinedTemporaryTableQueryConstructor(table, primaryTable, count = 0):
    if table == primaryTable or table.parentTable == None:
        return "select {ta}.{pc} as export_primary, {c} into temporary table {tempt} from {t} as {ta}{whereInclude} order by export_primary asc{order}".format(pc = table.keyColumn.name, c = ", ".join((countKeyColumnAlias() + "." if column.name in getAllColumnNamesFromTableName(table) else "") + column.name.format(alias = countKeyColumnAlias() + ".") for column in table.columns if column.include > 0), tempt = temporaryTableName(table), t = table.name, ta = countKeyColumnAlias(), whereInclude = " where " + primaryTable.whereInclude.format(alias = countKeyColumnAlias()) if not (primaryTable.whereInclude == "" or primaryTable.whereInclude == None) else "", order = (", " + ", ".join(order[0] + " " + ("asc" if order[1] == True else "desc") for order in table.orderBy)) if not (table.orderBy == None or len(table.orderBy) == 0) else "", alias = countKeyColumnAlias() + ".")
    else:
        return "select {refa}.export_primary as export_primary, {c} into temporary table {tempt} from {t} as {ta} inner join {reft} as {refa} on {ta}.{kc} = {refa}.{refkc} order by export_primary asc{order}".format(refa = countKeyColumnAlias(1), c = ", ".join(countKeyColumnAlias() + "." + column.name for column in table.columns if column.include > 0), tempt = temporaryTableName(table), t = table.name, ta = countKeyColumnAlias(), reft = temporaryTableName(table.parentTable), kc = table.keyColumn.name, refkc = table.parentKeyColumn.name, order = (", " + ", ".join(order[0] + " " + ("asc" if order[1] == True else "desc") for order in table.orderBy)) if not (table.orderBy == None or len(table.orderBy) == 0) else "")"""

def queryNextBuffer(table, size, offset):
    """
    Queries the database for the next batch of the temporary table.
    
    Takes the table object that corresponds to the temporary table, the size of the batch, and the starting position of the batch. Returns a list of tuples, with one tuple corresponding to one row.
    """
    success = runQuery("select export_primary, {c} from {t} where export_id >= {o} order by export_primary asc{order} limit {s}".format(c = ", ".join(column.name.format(alias = "") for column in table.columns if column.include == 2), t = temporaryTableName(table), o = offset, order = (", " + ", ".join(order[0] + " " + ("asc" if order[1] == True else "desc") for order in table.orderBy)) if not (table.orderBy == None or len(table.orderBy) == 0) else "", s = size))
    if success:
        return cursor.fetchall()
    else:
        return None

def temporaryTableName(table):
    """
    Takes a table object and returns the name of the corresponding temporary table as a string.
    """
    return table.name + "_export_temp"

def updateMaxEntries():
    """
    Updates the maxEntries variable for each table in the tableInfo list.
    """
    bar = Bar("Tables", max = len(tableInfo) - 1)
    for i in range(1, len(tableInfo)):
        if not tableInfo[i].forceOneToOne:
            bar.next()
            tableInfo[i].maxEntries = countMaxEntriesWithKeyColumn(tableInfo[i])
    for i in range(1, len(tableInfo)):
        if tableInfo[i].forceOneToOne:
            bar.next()
            tableInfo[i].maxEntries = tableInfo[i].parentTable.maxEntries
    bar.finish()

def writeColumnHeaders(file):
    """
    Writes the column headers to the export csv file.
    """
    bar = Bar("Tables        ", max = len(tableInfo))
    for table in tableInfo:
        bar.next()
        for i in range(table.maxEntries):
            for column in table.columns:
                if column.include == 2:
                    file.write(column.displayName + (str(i) if table.maxEntries > 1 else "") + ",")
    file.seek(file.tell() - 1)
    file.write("\n")
    bar.finish()

def queryPrimaryKeys():
    """
    Returns a list of all the keys for the primary table.
    """
    query = "select {c} from {t}"
    if not (tableInfo[0].whereInclude == None or tableInfo[0].whereInclude == ""):
        query += " where {w}"
    success = runQuery(query.format(c = tableInfo[0].keyColumn.name, t = tableInfo[0].name, w = tableInfo[0].whereInclude))
    if success:
        primaryKeys = cursor.fetchall()
        return [key[0] for key in primaryKeys]
    else:
        raise PrimaryKeyFetchException()

def countPrimaryKeys():
    """
    Counts the total number of included primary keys for the primary table."
    """
    query = "select count(*) from {t}"
    if not (tableInfo[0].whereInclude == None or tableInfo[0].whereInclude == ""):
        query += " where {w}"
    runQuery(query.format(t = tableInfo[0].name, w = tableInfo[0].whereInclude))
    if success:
        return cursor.fetchall()[0][0]
    else:
        raise PrimaryKeyFetchException()

#
# Custom exceptions
#

class NoPrimaryTableException(Exception):
    """
    Custom exception thrown when secondary tables are added without a primary table.
    """
    pass

class PrimaryKeyFetchException(Exception):
    """
    Custom exception thrown when a query fails while trying to retrieve a collection of primary keys.
    """
    pass