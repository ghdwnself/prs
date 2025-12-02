import { initializeApp } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-app.js";
import { getFirestore, doc, getDoc, collection, addDoc, serverTimestamp, query, where, getDocs } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-firestore.js";
import { getAuth, signInWithEmailAndPassword, onAuthStateChanged, signOut } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js";

const firebaseConfig = {
    apiKey: "AIzaSyBipMbpLpvOoY9cM7cwpmkEu7syx54tURI",
    authDomain: "hl-erp-80944.firebaseapp.com",
    projectId: "hl-erp-80944",
    storageBucket: "hl-erp-80944.firebasestorage.app",
    messagingSenderId: "366171644894",
    appId: "1:366171644894:web:221510b5007a1bace6334f",
    measurementId: "G-EZ3LZ6NG15"
};

const app = initializeApp(firebaseConfig);
const db = getFirestore(app);
const auth = getAuth(app);

export { app, db, auth, doc, getDoc, collection, addDoc, serverTimestamp, query, where, getDocs, signInWithEmailAndPassword, onAuthStateChanged, signOut };
