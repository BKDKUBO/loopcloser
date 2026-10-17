// Firestore security rules tests. Run with the emulator:
//   cd firestore-tests && npm run test:emulator
import { readFileSync } from "node:fs";
import { after, before, beforeEach, test } from "node:test";
import { assertFails, assertSucceeds, initializeTestEnvironment } from "@firebase/rules-unit-testing";
import { doc, getDoc, setDoc, deleteDoc, updateDoc } from "firebase/firestore";

let env;
const as = (uid, role) => env.authenticatedContext(uid, role ? { role } : {}).firestore();

before(async () => {
  env = await initializeTestEnvironment({
    projectId: "demo-loopcloser",
    firestore: { rules: readFileSync(new URL("../firestore.rules", import.meta.url), "utf8") },
  });
});
after(async () => env.cleanup());

beforeEach(async () => {
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await setDoc(doc(db, "cases/C-1"), { owner: "worker-1", backup_owner: null, patient_uid: "patient-1", state: "reviewed" });
    await setDoc(doc(db, "cases/C-1/events/000001"), { seq: 1, type: "case_opened" });
    await setDoc(doc(db, "users/worker-1"), { role: "worker" });
  });
});

test("unauthenticated users read nothing", async () => {
  await assertFails(getDoc(doc(env.unauthenticatedContext().firestore(), "cases/C-1")));
});

test("signed-in user without a role reads nothing", async () => {
  await assertFails(getDoc(doc(as("x"), "cases/C-1")));
});

test("coordinator, supervisor and program manager read cases and events", async () => {
  for (const r of ["coordinator", "supervisor", "program_manager"]) {
    await assertSucceeds(getDoc(doc(as("u-" + r, r), "cases/C-1")));
    await assertSucceeds(getDoc(doc(as("u-" + r, r), "cases/C-1/events/000001")));
  }
});

test("worker reads only assigned cases", async () => {
  await assertSucceeds(getDoc(doc(as("worker-1", "worker"), "cases/C-1")));
  await assertSucceeds(getDoc(doc(as("worker-1", "worker"), "cases/C-1/events/000001")));
  await assertFails(getDoc(doc(as("worker-2", "worker"), "cases/C-1")));
  await assertFails(getDoc(doc(as("worker-2", "worker"), "cases/C-1/events/000001")));
});

test("patient reads only their own case and never the event log", async () => {
  await assertSucceeds(getDoc(doc(as("patient-1", "patient"), "cases/C-1")));
  await assertFails(getDoc(doc(as("patient-2", "patient"), "cases/C-1")));
  await assertFails(getDoc(doc(as("patient-1", "patient"), "cases/C-1/events/000001")));
});

test("nobody writes cases or events from a client, even a supervisor", async () => {
  const db = as("sup", "supervisor");
  await assertFails(setDoc(doc(db, "cases/C-2"), { state: "closed" }));
  await assertFails(updateDoc(doc(db, "cases/C-1"), { state: "closed" }));
  await assertFails(setDoc(doc(db, "cases/C-1/events/000002"), { seq: 2 }));
  await assertFails(updateDoc(doc(db, "cases/C-1/events/000001"), { type: "x" }));
  await assertFails(deleteDoc(doc(db, "cases/C-1/events/000001")));
});

test("users read only their own profile", async () => {
  await assertSucceeds(getDoc(doc(as("worker-1", "worker"), "users/worker-1")));
  await assertFails(getDoc(doc(as("worker-2", "worker"), "users/worker-1")));
});

test("unknown collections are denied", async () => {
  await assertFails(getDoc(doc(as("sup", "supervisor"), "secrets/x")));
});
