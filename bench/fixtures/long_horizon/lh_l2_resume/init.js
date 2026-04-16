// Pre-seed localStorage with a partial todo list so the agent has to
// "resume" the workflow — 5 items, 2 already complete, 3 pending.
(function () {
  const seed = [
    { title: "Buy groceries",      completed: true  },
    { title: "Pay electricity bill", completed: false },
    { title: "Call dentist",       completed: false },
    { title: "Read book chapter",  completed: true  },
    { title: "Walk the dog",       completed: false },
  ];
  try {
    localStorage.setItem("todos-vanilla", JSON.stringify(seed));
  } catch (_e) { /* seed fails → agent will see an empty list and FAIL */ }
})();
