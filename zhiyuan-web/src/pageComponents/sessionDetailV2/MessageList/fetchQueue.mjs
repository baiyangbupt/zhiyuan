export function createFetchQueue(runner) {
  let inFlight = false;
  let pendingPage = null;

  const run = async page => {
    if (inFlight) {
      pendingPage = page ?? 1;
      return;
    }

    inFlight = true;
    try {
      await runner(page);
    } finally {
      inFlight = false;
      if (pendingPage !== null) {
        const nextPage = pendingPage;
        pendingPage = null;
        void run(nextPage);
      }
    }
  };

  return {
    enqueue(page) {
      return run(page);
    },
  };
}

