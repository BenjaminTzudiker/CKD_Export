from main import *

# Set these values to those used by your database
dbuser = "benjamintzudiker"
dbpass = ""
dbname = "ckd"
dbhost = "localhost"

# Attempts to connect to the database
cursor = connect(dbuser, dbpass, dbname, dbhost)

#if runQuery("select * from site_source"):
#    for row in cursor.fetchall():
#        print(row)

"""primaryTableWhereStatement = "patient_id in (select distinct e1.patient_id from encounter e1 where exists (select 1 from diagnosis d1 where d1.encounter_id = e1.encounter_id and ((d1.icd_code like 'N17%' and d1.icd_type = 10) or (d1.icd_code like '584%' and d1.icd_type = 9))))"
setupAddPrimaryTable("patient", keyColumnName = "patient_id", where = primaryTableWhereStatement)
setupAddSecondaryTable("encounter", keyColumnName = "patient_id", parentTableName = "patient", parentKeyColumnName = "patient_id")
setupAddSecondaryTable("diagnosis", keyColumnName = "encounter_id", parentTableName = "encounter", parentKeyColumnName = "encounter_id")"""

setupAddPrimaryTable("site_source", keyColumnName = "site_source")
setupAddSecondaryTable("site_source_test", keyColumnName = "site_source", parentTableName = "site_source", parentKeyColumnName = "site_source")

run(mode = "slow")

# Closes the database connection
close()