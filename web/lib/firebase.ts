import { initializeApp, getApps, type FirebaseApp } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";

// Firebase web config is public by design. Access is enforced by Auth, the API and Firestore rules.
let app: FirebaseApp | undefined;

export function firebaseAuth(): Auth {
  if (!app) {
    app = getApps()[0] ?? initializeApp({
      apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
      authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
      projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    });
  }
  return getAuth(app);
}
