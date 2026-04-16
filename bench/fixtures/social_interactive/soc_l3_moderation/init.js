// Seed two initial messages — one from "You" (so we can edit it) and one
// from Alice (read-only to us). Read by index.html on DOMContentLoaded.
window.__SEED_MSGS__ = [
  {
    id: "m1",
    author: "You",
    text: "Initial note — I'll update this shortly.",
    edited: false,
    deleted: false,
  },
  {
    id: "m2",
    author: "Alice",
    text: "Typo in my last message, please ignore.",
    edited: false,
    deleted: false,
  },
];
