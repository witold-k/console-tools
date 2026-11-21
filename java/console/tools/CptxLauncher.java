package console.tools;

import java.io.*;
import java.lang.invoke.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.wasm2jar.Function;
import org.wasm2jar.Memory;

/** Minimal WASI Preview 1 host for the std-only cptx WASM module. */
public final class CptxLauncher {
    private static final int SUCCESS = 0, BADF = 8, FAULT = 21, INVAL = 28, IO = 29;
    private static final int MAX_IOVECS = 65536;
    private Memory memory;
    private final String[] argv;
    private final String[] environment;

    private CptxLauncher(String[] args) {
        argv = new String[args.length + 1];
        argv[0] = "cptx";
        System.arraycopy(args, 0, argv, 1, args.length);
        environment = System.getenv().entrySet().stream()
            .map(e -> e.getKey() + "=" + e.getValue()).toArray(String[]::new);
    }

    private ByteBuffer mem() {
        if (memory == null) throw new IllegalStateException("WASM memory not initialized");
        return memory.bytes.duplicate().order(ByteOrder.LITTLE_ENDIAN);
    }
    private static void check(ByteBuffer m, long address, long length) {
        if (address < 0 || length < 0 || address + length > m.capacity())
            throw new IndexOutOfBoundsException("WASM memory access " + address + "+" + length);
    }
    private static long unsigned(int value) { return Integer.toUnsignedLong(value); }
    private static byte[][] encoded(String[] values) {
        byte[][] bytes = new byte[values.length][];
        for (int i = 0; i < values.length; i++) {
            byte[] raw = values[i].getBytes(StandardCharsets.UTF_8);
            bytes[i] = Arrays.copyOf(raw, raw.length + 1);
        }
        return bytes;
    }
    private int sizes(String[] values, int countPtr, int bytesPtr) {
        try {
            ByteBuffer m = mem();
            check(m, unsigned(countPtr), 4); check(m, unsigned(bytesPtr), 4);
            byte[][] entries = encoded(values);
            long total = 0;
            for (byte[] entry : entries) total += entry.length;
            if (total > Integer.MAX_VALUE) return INVAL;
            m.putInt(countPtr, entries.length);
            m.putInt(bytesPtr, (int) total);
            return SUCCESS;
        } catch (IndexOutOfBoundsException ex) { return FAULT; }
    }
    private int values(String[] strings, int pointers, int buffer) {
        try {
            ByteBuffer m = mem();
            byte[][] entries = encoded(strings);
            long ptr = unsigned(pointers), dst = unsigned(buffer), total = 0;
            for (byte[] entry : entries) total += entry.length;
            check(m, ptr, (long) entries.length * 4);
            check(m, dst, total);
            for (byte[] entry : entries) {
                m.putInt((int) ptr, (int) dst);
                ptr += 4;
                m.position((int) dst);
                m.put(entry);
                dst += entry.length;
            }
            return SUCCESS;
        } catch (IndexOutOfBoundsException | IllegalArgumentException ex) { return FAULT; }
    }
    public int args_sizes_get(int a, int b) { return sizes(argv, a, b); }
    public int args_get(int a, int b) { return values(argv, a, b); }
    public int environ_sizes_get(int a, int b) { return sizes(environment, a, b); }
    public int environ_get(int a, int b) { return values(environment, a, b); }

    public int fd_read(int fd, int iovs, int count, int nread) {
        if (fd != 0) return BADF;
        try {
            ByteBuffer m = mem();
            long base = unsigned(iovs), n = unsigned(count);
            if (n > MAX_IOVECS) return INVAL;
            check(m, base, n * 8); check(m, unsigned(nread), 4);
            int total = 0;
            for (int i = 0; i < n; i++) {
                int address = m.getInt((int) (base + i * 8L));
                long length = unsigned(m.getInt((int) (base + i * 8L + 4)));
                check(m, unsigned(address), length);
                if (length == 0) continue;
                int amount = (int) Math.min(length, 65536);
                byte[] data = new byte[amount];
                int read = System.in.read(data);
                if (read < 0) break;
                m.position(address); m.put(data, 0, read);
                total += read;
                if (read < amount) break;
            }
            m.putInt(nread, total);
            return SUCCESS;
        } catch (IOException ex) { return IO; }
          catch (IndexOutOfBoundsException | IllegalArgumentException ex) { return FAULT; }
    }
    public int fd_write(int fd, int iovs, int count, int nwritten) {
        if (fd != 1 && fd != 2) return BADF;
        try {
            ByteBuffer m = mem();
            long base = unsigned(iovs), n = unsigned(count);
            if (n > MAX_IOVECS) return INVAL;
            check(m, base, n * 8); check(m, unsigned(nwritten), 4);
            OutputStream stream = fd == 1 ? System.out : System.err;
            int total = 0;
            for (int i = 0; i < n; i++) {
                int address = m.getInt((int) (base + i * 8L));
                long length = unsigned(m.getInt((int) (base + i * 8L + 4)));
                check(m, unsigned(address), length);
                byte[] chunk = new byte[(int) Math.min(length, 65536)];
                long pos = unsigned(address);
                while (length > 0) {
                    int take = (int) Math.min(length, chunk.length);
                    m.position((int) pos); m.get(chunk, 0, take);
                    stream.write(chunk, 0, take);
                    pos += take; length -= take; total += take;
                }
            }
            stream.flush();
            // PrintStream suppresses IOException; expose failures as WASI IO.
            if (stream instanceof PrintStream && ((PrintStream) stream).checkError()) return IO;
            m.putInt(nwritten, total);
            return SUCCESS;
        } catch (IOException ex) { return IO; }
          catch (IndexOutOfBoundsException | IllegalArgumentException ex) { return FAULT; }
    }
    private static final class Exit extends RuntimeException {
        final int status;
        Exit(int status) { super(null, null, false, false); this.status = status; }
    }
    public void proc_exit(int status) { throw new Exit(status); }

    private Map<String, Map<String, Object>> imports() throws ReflectiveOperationException {
        MethodHandles.Lookup lookup = MethodHandles.lookup();
        Map<String, Object> wasi = new HashMap<>();
        for (String name : new String[] {
                "args_sizes_get", "args_get", "environ_sizes_get", "environ_get",
                "fd_read", "fd_write", "proc_exit" }) {
            int arity = name.equals("proc_exit") ? 1
                : (name.equals("fd_read") || name.equals("fd_write") ? 4 : 2);
            Class<?>[] parameters = new Class<?>[arity];
            Arrays.fill(parameters, int.class);
            Class<?> result = name.equals("proc_exit") ? void.class : int.class;
            MethodHandle handle = lookup.findVirtual(CptxLauncher.class, name,
                MethodType.methodType(result, parameters)).bindTo(this);
            wasi.put(name, new Function(handle));
        }
        return Collections.singletonMap("wasi_snapshot_preview1", wasi);
    }
    private int execute() throws Exception {
        Cptx program = new Cptx(imports());
        Object exported = program.exports.get("memory");
        if (!(exported instanceof Memory))
            throw new IllegalStateException("WASM memory export missing: " + program.exports.keySet());
        memory = (Memory) exported;
        try {
            program._start();
            return 0;
        } catch (Exit exit) {
            return exit.status;
        }
    }
    private static byte[] commandOutput(String... command) throws Exception {
        Process process = new ProcessBuilder(command).start();
        byte[] stdout = process.getInputStream().readAllBytes();
        byte[] stderr = process.getErrorStream().readAllBytes();
        int status = process.waitFor();
        if (status != 0)
            throw new IOException(command[0] + " exited " + status + ": "
                + new String(stderr, StandardCharsets.UTF_8));
        return stdout;
    }

    /** Match the clipboard backend selection and fallback used by xcat. */
    private static void copyToClipboard(byte[] bytes) throws IOException, InterruptedException {
        List<String[]> candidates = new ArrayList<>();
        if (System.getenv("WAYLAND_DISPLAY") != null)
            candidates.add(new String[]{"wl-copy", "--type", "text/plain;charset=utf-8"});
        if (System.getenv("DISPLAY") != null) {
            candidates.add(new String[]{"xclip", "-selection", "clipboard"});
            candidates.add(new String[]{"xsel", "--clipboard", "--input"});
        }
        if (candidates.isEmpty()) {
            candidates.add(new String[]{"wl-copy", "--type", "text/plain;charset=utf-8"});
            candidates.add(new String[]{"xclip", "-selection", "clipboard"});
            candidates.add(new String[]{"xsel", "--clipboard", "--input"});
        }
        List<String> errors = new ArrayList<>();
        for (String[] command : candidates) {
            try {
                Process process = new ProcessBuilder(command)
                    .redirectOutput(ProcessBuilder.Redirect.DISCARD)
                    .redirectError(ProcessBuilder.Redirect.DISCARD).start();
                try (OutputStream sink = process.getOutputStream()) {
                    sink.write(bytes);
                }
                int status = process.waitFor();
                if (status == 0) return;
                errors.add(command[0] + " exited " + status);
            } catch (IOException error) {
                errors.add(command[0] + ": " + error.getMessage());
            }
        }
        throw new IOException("Clipboard unavailable (" + String.join("; ", errors) + ")");
    }

    /** Desktop mode: tmux -> original Rust WASM logic -> OS clipboard. */
    private static void desktop() throws Exception {
        byte[] pane = commandOutput("tmux", "capture-pane", "-p", "-S", "-");
        InputStream originalIn = System.in;
        PrintStream originalOut = System.out;
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try {
            System.setIn(new ByteArrayInputStream(pane));
            System.setOut(new PrintStream(output, true, StandardCharsets.UTF_8));
            int status = new CptxLauncher(new String[0]).execute();
            if (status != 0) throw new IOException("Rust WASM cptx exited " + status);
        } finally {
            System.setIn(originalIn);
            System.setOut(originalOut);
        }
        byte[] bytes = output.toByteArray();
        copyToClipboard(bytes);
    }

    public static void main(String[] args) {
        try {
            if (args.length == 1 && "--desktop".equals(args[0])) { desktop(); return; }
            int status = new CptxLauncher(args).execute();
            if (status != 0) System.exit(status);
        } catch (Throwable error) {
            System.err.println("cptx JVM host: " + error);
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }
}
