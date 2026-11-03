import { MongoClient, Db } from "mongodb";

const DIRECT_REPLICA_URI =
  "mongodb://official4basha_db_user:xui37tp9xiymeCTf@ac-eu5fin0-shard-00-00.ymalimp.mongodb.net:27017,ac-eu5fin0-shard-00-01.ymalimp.mongodb.net:27017,ac-eu5fin0-shard-00-02.ymalimp.mongodb.net:27017/AI_Automation_Forms?ssl=true&replicaSet=atlas-8emrh7-shard-0&authSource=admin&retryWrites=true&w=majority";

function getCandidateUris(): string[] {
  let u = (process.env.MONGODB_URI || "").trim();
  if (
    (u.startsWith('"') && u.endsWith('"')) ||
    (u.startsWith("'") && u.endsWith("'"))
  ) {
    u = u.slice(1, -1).trim();
  }

  const list: string[] = [];
  // Prefer the direct replica set URI on cloud/serverless to bypass SRV DNS TLS alerts
  list.push(DIRECT_REPLICA_URI);

  if (u && u !== DIRECT_REPLICA_URI) {
    list.push(u);
  } else {
    list.push(
      "mongodb+srv://official4basha_db_user:xui37tp9xiymeCTf@cluster0.ymalimp.mongodb.net/?retryWrites=true&w=majority"
    );
  }

  return list;
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

  const uris = getCandidateUris();
  let lastError: any = null;

  for (const uri of uris) {
    try {
      const client = new MongoClient(uri, {
        maxPoolSize: 10,
        serverSelectionTimeoutMS: 6000,
        connectTimeoutMS: 6000,
        socketTimeoutMS: 20000,
        retryWrites: true,
      });

      await client.connect();
      const db = client.db(dbName);

      cachedClient = client;
      cachedDb = db;
      return { client, db };
    } catch (err) {
      lastError = err;
      continue;
    }
  }

  cachedClient = null;
  cachedDb = null;
  throw lastError || new Error("Failed to connect to MongoDB Atlas");
}
