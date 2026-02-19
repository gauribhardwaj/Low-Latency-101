public class SystemOutNewLoop {
  public static void main(String[] args) {
    for (int i = 0; i < 1000; i++) {
      System.out.println("i=" + i);
      Object o = new Object();
    }
  }
}

