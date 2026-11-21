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

    private CptxLauncher(String[] args) { this(args, false); }

    private CptxLauncher(String[] args, boolean desktop) {
        argv = new String[args.length + 1];
        argv[0] = "cptx";
        System.arraycopy(args, 0, argv, 1, args.length);
        List<String> vars = new ArrayList<>();
        System.getenv().forEach((k, v) -> vars.add(k + "=" + v));
        if (desktop) vars.add("CONSOLE_TOOLS_JVM_CLIPBOARD=1");
        environment = vars.toArray(String[]::new);
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

    /** Execute only the commands selected by Rust; no clipboard policy in Java. */
    private static void copyToClipboard(byte[] data) throws IOException, InterruptedException {
        byte[] magic = new byte[]{'C','T','C','L','I','P','1',0};
        if (data.length < magic.length + 1)
            throw new IOException("Missing Rust clipboard host protocol");
        for (int i = 0; i < magic.length; i++)
            if (data[i] != magic[i])
                throw new IOException("Invalid Rust clipboard host protocol");
        int pos = magic.length;
        int count = Byte.toUnsignedInt(data[pos++]);
        if (count < 1 || count > 8) throw new IOException("Invalid clipboard candidate count");
        List<String[]> commands = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            List<String> argv = new ArrayList<>();
            int start = pos;
            while (pos < data.length && data[pos] != 0) pos++;
            if (pos >= data.length || pos == start) throw new IOException("Invalid clipboard command");
            argv.add(new String(data, start, pos - start, StandardCharsets.UTF_8));
            pos++;
            if (pos >= data.length) throw new IOException("Missing clipboard argument count");
            int argc = Byte.toUnsignedInt(data[pos++]);
            if (argc > 8) throw new IOException("Invalid clipboard argument count");
            for (int j = 0; j < argc; j++) {
                start = pos;
                while (pos < data.length && data[pos] != 0) pos++;
                if (pos >= data.length) throw new IOException("Unterminated clipboard argument");
                argv.add(new String(data, start, pos - start, StandardCharsets.UTF_8));
                pos++;
            }
            commands.add(argv.toArray(String[]::new));
        }
        byte[] payload = Arrays.copyOfRange(data, pos, data.length);
        runClipboardCommands(commands, payload);
    }

    private static void runClipboardCommands(List<String[]> commands, byte[] payload)
            throws IOException, InterruptedException {
        List<String> errors = new ArrayList<>();
        for (String[] command : commands) {
            try {
                Process process = new ProcessBuilder(command)
                    .redirectOutput(ProcessBuilder.Redirect.DISCARD)
                    .redirectError(ProcessBuilder.Redirect.DISCARD).start();
                try (OutputStream sink = process.getOutputStream()) {
                    sink.write(payload);
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

    private static boolean hasClipboardEnvelope(byte[] data) {
        byte[] magic = new byte[]{'C','T','C','L','I','P','1',0};
        if (data.length < magic.length + 1) return false;
        for (int i = 0; i < magic.length; i++)
            if (data[i] != magic[i]) return false;
        return true;
    }

    /** Compatibility bridge for the experimental no_std module only. */
    private static void copyRawNoStdToClipboard(byte[] data)
            throws IOException, InterruptedException {
        List<String[]> commands = new ArrayList<>();
        if (System.getenv("WAYLAND_DISPLAY") != null)
            commands.add(new String[]{"wl-copy", "--type", "text/plain;charset=utf-8"});
        if (System.getenv("DISPLAY") != null) {
            commands.add(new String[]{"xclip", "-selection", "clipboard"});
            commands.add(new String[]{"xsel", "--clipboard", "--input"});
        }
        if (commands.isEmpty()) {
            commands.add(new String[]{"wl-copy", "--type", "text/plain;charset=utf-8"});
            commands.add(new String[]{"xclip", "-selection", "clipboard"});
            commands.add(new String[]{"xsel", "--clipboard", "--input"});
        }
        runClipboardCommands(commands, data);
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
            int status = new CptxLauncher(new String[0], true).execute();
            if (status != 0) throw new IOException("Rust WASM cptx exited " + status);
        } finally {
            System.setIn(originalIn);
            System.setOut(originalOut);
        }
        byte[] bytes = output.toByteArray();
        // The experimental no_std WASI module emits raw UTF-8 rather than
        // the CTCLIP1 envelope used by the regular Rust WASI implementation.
        // Validate the complete capture before allowing any clipboard side effect.
        if (!hasClipboardEnvelope(bytes)) {
            java.nio.charset.CharsetDecoder decoder = StandardCharsets.UTF_8.newDecoder()
                .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
                .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT);
            try {
                decoder.decode(ByteBuffer.wrap(bytes));
            } catch (java.nio.charset.CharacterCodingException ex) {
                throw new IOException("cptx: invalid UTF-8", ex);
            }
            copyRawNoStdToClipboard(bytes);
        } else {
            copyToClipboard(bytes);
        }
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
