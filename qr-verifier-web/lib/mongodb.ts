import { MongoClient, Db } from "mongodb";

const uri = process.env.MONGODB_URI || "mongodb+srv://official4basha_db_user:xui37tp9xiymeCTf@cluster0.ymalimp.mongodb.net/";
const dbName = process.env.MONGODB_DB || "AI_Automation_Forms";

let cachedClient: MongoClient | null = null;
let cachedDb: Db | null = null;

export async function connectToDatabase(): Promise<{ client: MongoClient; db: Db }> {
  if (cachedClient && cachedDb) {
    return { client: cachedClient, db: cachedDb };
  }

  const client = new MongoClient(uri, {
    maxPoolSize: 10,
    serverSelectionTimeoutMS: 5000,
  });

  await client.connect();
  const db = client.db(dbName);

  cachedClient = client;
  cachedDb = db;

  return { client, db };
}

