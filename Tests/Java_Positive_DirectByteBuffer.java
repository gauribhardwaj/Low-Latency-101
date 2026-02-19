import java.nio.ByteBuffer;

public class DirectBuffer {
  public static void main(String[] args) {
    ByteBuffer buf = ByteBuffer.allocateDirect(1024);
  }
}

