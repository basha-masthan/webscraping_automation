import { MongoClient, Db } from "mongodb";

function getCleanUri(): string {
  let u = (process.env.MONGODB_URI || "").trim();
  if (
    (u.startsWith('"') && u.endsWith('"')) ||
    (u.startsWith("'") && u.endsWith("'"))
  ) {
    u = u.slice(1, -1).trim();
  }
  if (!u) {
    u =
      "mongodb+srv://official4basha_db_user:xui37tp9xiymeCTf@cluster0.ymalimp.mongodb.net/?retryWrites=true&w=majority";
  }
  return u;
}

const dbName = (process.env.MONGODB_DB || "AI_Automation_Forms").trim();

let cachedClient: MongoClient | null = null;
let cachedDb: Db | null = null;

export async function connectToDatabase(): Promise<{ client: MongoClient; db: Db }> {
  if (cachedClient && cachedDb) {
    try {
      await cachedDb.command({ ping: 1 });
      return { client: cachedClient, db: cachedDb };
    } catch {
      cachedClient = null;
      cachedDb = null;
    }
  }

  const uri = getCleanUri();
  const client = new MongoClient(uri, {
    maxPoolSize: 10,
    serverSelectionTimeoutMS: 10000,
    connectTimeoutMS: 10000,
    socketTimeoutMS: 20000,
    retryWrites: true,
  });

  try {
    await client.connect();
    const db = client.db(dbName);
    cachedClient = client;
    cachedDb = db;
    return { client, db };
  } catch (err) {
    cachedClient = null;
    cachedDb = null;
    throw err;
  }
}
