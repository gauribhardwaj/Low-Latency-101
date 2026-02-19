public class SyncHotPath {
  private int x = 0;

  public synchronized void inc() { x++; }

  public void spin() {
    for (int i = 0; i < 1000; i++) {
      synchronized (this) { x++; }
    }
  }
}

