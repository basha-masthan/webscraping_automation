import { MongoClient, Db } from "mongodb";

const uri =
  process.env.MONGODB_URI ||
  "mongodb+srv://official4basha_db_user:xui37tp9xiymeCTf@cluster0.ymalimp.mongodb.net/?retryWrites=true&w=majority";

const dbName = process.env.MONGODB_DB || "AI_Automation_Forms";

declare global {
  // eslint-disable-next-line no-var
  var _mongoClientPromise: Promise<MongoClient> | undefined;
}

let clientPromise: Promise<MongoClient>;

if (!global._mongoClientPromise) {
  const client = new MongoClient(uri, {
    maxPoolSize: 10,
    serverSelectionTimeoutMS: 8000,
  });
  global._mongoClientPromise = client.connect();
}
clientPromise = global._mongoClientPromise;

export async function connectToDatabase(): Promise<{ client: MongoClient; db: Db }> {
  const client = await clientPromise;
  const db = client.db(dbName);
  return { client, db };
}
