// "The session has expired" signal. The API client raises it when the
// controller answers 401; the AuthGate listens and shows the login screen.
type Listener = () => void;

const listeners = new Set<Listener>();

/** Call ``listener`` at each expiry; returns the function that stops listening. */
export function onSessionExpired(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function notifySessionExpired(): void {
  for (const listener of listeners) {
    listener();
  }
}
