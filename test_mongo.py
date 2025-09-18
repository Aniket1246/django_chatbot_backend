from pymongo import MongoClient

client = MongoClient(
    "mongodb+srv://d2023amitramtri_db_user:0aGLD4KQoCwBmrwI@ukjobsinsider.mzj7olb.mongodb.net/?retryWrites=true&w=majority&appName=ukjobsinsider",
    tls=True,
    tlsAllowInvalidCertificates=True
)
print(client.list_database_names())
