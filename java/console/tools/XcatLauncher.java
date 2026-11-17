package console.tools;

import java.io.*;
import java.lang.invoke.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.*;
import java.util.*;
import org.wasm2jar.Function;
import org.wasm2jar.Memory;

/** Minimal WASI Preview 1 host for the std-only xcat WASM module. */
public final class XcatLauncher {
    private static final int SUCCESS = 0, BADF = 8, FAULT = 21, INVAL = 28, IO = 29, NOSYS = 52;
    private static final int MAX_IOVECS = 65536;
    private Memory memory;
    private final Map<Integer,Path> paths=new HashMap<>();
    private final Map<Integer,Long> offsets=new HashMap<>();
    private final ByteArrayOutputStream output=new ByteArrayOutputStream();
    private int nextFd=5;
    private final Path root=Paths.get("").toAbsolutePath().normalize();
    private final Path cfg=Paths.get(System.getenv().getOrDefault("XDG_CONFIG_HOME",
        Paths.get(System.getProperty("user.home"),".config").toString())).toAbsolutePath().normalize().resolve("xcat");
    private final String[] argv;
    private final String[] environment;

    private XcatLauncher(String[] args) {
        paths.put(3,root);paths.put(4,cfg);
        List<String> a=new ArrayList<>(Arrays.asList(args));
        if(!a.contains("--help")&&!a.contains("-h")){
            if(!a.contains("-d")&&!a.contains("--dir")){a.add("-d");a.add(".");}
            if(!a.contains("-c")&&!a.contains("--config")){a.add("-c");a.add("/cfg/config.json");}
        }
        argv = new String[a.size()+1];argv[0]="xcat";
        for(int i=0;i<a.size();i++)argv[i+1]=a.get(i);
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
        if (fd != 0 && !paths.containsKey(fd)) return BADF;
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
                int read;
                if(fd==0)read=System.in.read(data);
                else {Path p=paths.get(fd);try(RandomAccessFile f=new RandomAccessFile(p.toFile(),"r")){long off=offsets.getOrDefault(fd,0L);f.seek(off);read=f.read(data);if(read>0)offsets.put(fd,off+read);}}
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
        if (fd != 1 && fd != 2 && !paths.containsKey(fd)) return BADF;
        try {
            ByteBuffer m = mem();
            long base = unsigned(iovs), n = unsigned(count);
            if (n > MAX_IOVECS) return INVAL;
            check(m, base, n * 8); check(m, unsigned(nwritten), 4);
            OutputStream stream = fd == 2 ? System.err : null;
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
                    if(fd==1)output.write(chunk,0,take);
                    if(fd==1) { /* stdout was already captured above */ }
                    else if(stream!=null)stream.write(chunk,0,take);
                    else {try(RandomAccessFile f=new RandomAccessFile(paths.get(fd).toFile(),"rw")){long off=offsets.getOrDefault(fd,0L);f.seek(off);f.write(chunk,0,take);offsets.put(fd,off+take);}}
                    pos += take; length -= take; total += take;
                }
            }
            if(stream!=null)stream.flush();
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

    public int random_get(int address, int length) {
        try {
            ByteBuffer m = mem();
            long n = unsigned(length);
            check(m, unsigned(address), n);
            byte[] chunk = new byte[(int) Math.min(n, 65536)];
            java.security.SecureRandom random = new java.security.SecureRandom();
            long pos = unsigned(address);
            while (n > 0) {
                int take = (int) Math.min(n, chunk.length);
                random.nextBytes(chunk);
                m.position((int) pos);
                m.put(chunk, 0, take);
                pos += take;
                n -= take;
            }
            return SUCCESS;
        } catch (IndexOutOfBoundsException | IllegalArgumentException ex) { return FAULT; }
    }


    private Path path(int fd,int ptr,int len) throws IOException {
        Path base=paths.get(fd);if(base==null)throw new NoSuchFileException("fd "+fd);
        ByteBuffer m=mem();check(m,unsigned(ptr),unsigned(len));
        byte[] b=new byte[len];m.position(ptr);m.get(b);
        String name=new String(b,StandardCharsets.UTF_8);
        if(name.startsWith("/"))throw new AccessDeniedException(name);
        Path p=base.resolve(name).normalize();
        Path allowed=fd==4||base.startsWith(cfg)?cfg:root;
        if(!p.startsWith(allowed))throw new AccessDeniedException(name);
        Path cursor=allowed;
        for(Path part:allowed.relativize(p)){
            cursor=cursor.resolve(part);
            if(Files.isSymbolicLink(cursor))throw new AccessDeniedException(name);
        }
        return p;
    }
    private int error(Exception e){
        if(e instanceof NoSuchFileException)return 44;
        if(e instanceof AccessDeniedException)return 76;
        if(e instanceof FileAlreadyExistsException)return 20;
        return IO;
    }
    public int fd_prestat_get(int fd,int ptr){
        if(fd!=3&&fd!=4)return BADF;
        try{ByteBuffer m=mem();check(m,unsigned(ptr),8);m.putInt(ptr,0);
            m.putInt(ptr+4,fd==3?1:4);return 0;}
        catch(IndexOutOfBoundsException e){return FAULT;}
    }
    public int fd_prestat_dir_name(int fd,int ptr,int len){
        if(fd!=3&&fd!=4)return BADF;
        byte[] b=(fd==3?".":"/cfg").getBytes(StandardCharsets.UTF_8);
        if(len<b.length)return INVAL;
        try{ByteBuffer m=mem();check(m,unsigned(ptr),b.length);m.position(ptr);m.put(b);return 0;}
        catch(IndexOutOfBoundsException e){return FAULT;}
    }
    public int fd_fdstat_get(int fd,int ptr){
        if(fd>2&&!paths.containsKey(fd))return BADF;
        try{ByteBuffer m=mem();check(m,unsigned(ptr),24);
            for(int i=0;i<24;i++)m.put(ptr+i,(byte)0);
            m.put(ptr,(byte)(fd<3?2:Files.isDirectory(paths.get(fd))?3:4));
            m.putLong(ptr+8,0x1fffffffL);m.putLong(ptr+16,0x1fffffffL);return 0;}
        catch(IndexOutOfBoundsException e){return FAULT;}
    }
    private void stat(Path p,int ptr)throws IOException{
        ByteBuffer m=mem();check(m,unsigned(ptr),64);
        BasicFileAttributes a=Files.readAttributes(p,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
        for(int i=0;i<64;i++)m.put(ptr+i,(byte)0);
        m.put(ptr+16,(byte)(a.isDirectory()?3:a.isRegularFile()?4:7));
        m.putLong(ptr+24,1);m.putLong(ptr+32,a.size());
        m.putLong(ptr+40,a.lastAccessTime().toMillis()*1000000);
        m.putLong(ptr+48,a.lastModifiedTime().toMillis()*1000000);
        m.putLong(ptr+56,a.creationTime().toMillis()*1000000);
    }
    public int fd_filestat_get(int fd,int ptr){
        if(!paths.containsKey(fd))return BADF;
        try{stat(paths.get(fd),ptr);return 0;}
        catch(IndexOutOfBoundsException e){return FAULT;}
        catch(IOException e){return error(e);}
    }
    public int path_filestat_get(int fd,int flags,int ptr,int len,int out){
        try{stat(path(fd,ptr,len),out);return 0;}
        catch(IndexOutOfBoundsException e){return FAULT;}
        catch(IOException e){return error(e);}
    }
    public int path_open(int fd,int dirflags,int ptr,int len,int flags,long rights,long inherited,int fdflags,int out){
        try{Path p=path(fd,ptr,len);ByteBuffer m=mem();check(m,unsigned(out),4);
            if((flags&1)!=0){Files.createDirectories(p.getParent());
                try{Files.createFile(p);}catch(FileAlreadyExistsException e){if((flags&4)!=0)throw e;}}
            if(!Files.exists(p,LinkOption.NOFOLLOW_LINKS))return 44;
            if((flags&2)!=0&&!Files.isDirectory(p))return 54;
            if((flags&8)!=0)Files.newByteChannel(p,StandardOpenOption.WRITE,StandardOpenOption.TRUNCATE_EXISTING).close();
            int id=nextFd++;paths.put(id,p);offsets.put(id,0L);m.putInt(out,id);return 0;
        }catch(IndexOutOfBoundsException e){return FAULT;}
        catch(IOException e){return error(e);}
    }
    public int path_create_directory(int fd,int ptr,int len){
        try{Files.createDirectories(path(fd,ptr,len));return 0;}
        catch(IndexOutOfBoundsException e){return FAULT;}
        catch(IOException e){return error(e);}
    }
    public int path_readlink(int fd,int p,int n,int b,int size,int used){return INVAL;}
    public int fd_close(int fd){
        if(fd<5||!paths.containsKey(fd))return BADF;
        paths.remove(fd);offsets.remove(fd);return 0;
    }
    public int fd_readdir(int fd,int ptr,int len,long cookie,int used){
        Path p=paths.get(fd);if(p==null)return BADF;
        if(!Files.isDirectory(p))return 54;
        try{ByteBuffer m=mem();check(m,unsigned(ptr),unsigned(len));check(m,unsigned(used),4);
            List<Path> entries=new ArrayList<>();
            try(DirectoryStream<Path> ds=Files.newDirectoryStream(p)){for(Path e:ds)entries.add(e);}
            entries.sort(Comparator.comparing(e->e.getFileName().toString()));
            long pos=unsigned(ptr),end=pos+unsigned(len);
            for(int i=(int)Math.max(0,cookie);i<entries.size();i++){
                Path e=entries.get(i);
                byte[] name=e.getFileName().toString().getBytes(StandardCharsets.UTF_8);
                byte[] record=new byte[24+name.length];
                ByteBuffer r=ByteBuffer.wrap(record).order(ByteOrder.LITTLE_ENDIAN);
                r.putLong(0,i+1);r.putInt(16,name.length);
                r.put(20,(byte)(Files.isDirectory(e,LinkOption.NOFOLLOW_LINKS)?3:Files.isRegularFile(e,LinkOption.NOFOLLOW_LINKS)?4:7));
                System.arraycopy(name,0,record,24,name.length);
                int n=(int)Math.min(record.length,end-pos);if(n<=0)break;
                m.position((int)pos);m.put(record,0,n);pos+=n;if(n<record.length)break;
            }
            m.putInt(used,(int)(pos-unsigned(ptr)));return 0;
        }catch(IndexOutOfBoundsException e){return FAULT;}
        catch(IOException e){return error(e);}
    }

    // Remaining unsupported calls fail explicitly.
    // Return ENOSYS explicitly rather than allowing a missing import to
    // prevent even --help from starting.
    private static int unsupported(int... args) { return NOSYS; }

    private Map<String, Map<String, Object>> imports() throws ReflectiveOperationException {
        MethodHandles.Lookup lookup = MethodHandles.lookup();
        Map<String, Object> wasi = new HashMap<>();
        Map<String, Integer> arities = new LinkedHashMap<>();
        arities.put("args_sizes_get", 2);
        arities.put("args_get", 2);
        arities.put("environ_sizes_get", 2);
        arities.put("environ_get", 2);
        arities.put("fd_read", 4);
        arities.put("fd_write", 4);
        arities.put("proc_exit", 1);
        arities.put("random_get", 2);
        arities.put("fd_close", 1);
        arities.put("fd_fdstat_get", 2);
        arities.put("fd_filestat_get", 2);
        arities.put("fd_prestat_get", 2);
        arities.put("fd_prestat_dir_name", 3);
        arities.put("fd_readdir", 5);
        arities.put("path_create_directory", 3);
        arities.put("path_filestat_get", 5);
        arities.put("path_open", 9);
        arities.put("path_readlink", 6);
        for (Map.Entry<String, Integer> entry : arities.entrySet()) {
            String name = entry.getKey();
            int arity = entry.getValue();
            Class<?>[] parameters = new Class<?>[arity];
            Arrays.fill(parameters, int.class);
            if (name.equals("fd_readdir")) parameters[3] = long.class;
            if (name.equals("path_open")) {
                parameters[5] = long.class;
                parameters[6] = long.class;
            }
            Class<?> result = name.equals("proc_exit") ? void.class : int.class;
            MethodHandle handle;
            if (name.equals("proc_exit") || name.equals("random_get")
                    || name.equals("args_sizes_get") || name.equals("args_get")
                    || name.equals("environ_sizes_get") || name.equals("environ_get")
                    || name.equals("fd_read") || name.equals("fd_write")
                    || name.startsWith("fd_") || name.startsWith("path_")) {
                handle = lookup.findVirtual(XcatLauncher.class, name,
                    MethodType.methodType(result, parameters)).bindTo(this);
            } else {
                handle = MethodHandles.dropArguments(
                    MethodHandles.constant(int.class, NOSYS), 0, parameters);
            }
            wasi.put(name, new Function(handle));
        }
        return Collections.singletonMap("wasi_snapshot_preview1", wasi);
    }
    private int execute() throws Exception {
        Xcat program = new Xcat(imports());
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

    /** Desktop mode is reserved for the cptx stdin bridge. */
    private static void desktop() throws Exception {
        byte[] pane = commandOutput("tmux", "capture-pane", "-p", "-S", "-");
        InputStream originalIn = System.in;
        PrintStream originalOut = System.out;
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try {
            System.setIn(new ByteArrayInputStream(pane));
            System.setOut(new PrintStream(output, true, StandardCharsets.UTF_8));
            int status = new XcatLauncher(new String[0]).execute();
            if (status != 0) throw new IOException("Rust WASM xcat exited " + status);
        } finally {
            System.setIn(originalIn);
            System.setOut(originalOut);
        }
        byte[] bytes = output.toByteArray();
        String[] clipboard = System.getenv("WAYLAND_DISPLAY") != null
            ? new String[] {"wl-copy", "--type", "text/plain;charset=utf-8"}
            : new String[] {"xclip", "-selection", "clipboard"};
        Process process = new ProcessBuilder(clipboard)
            .redirectOutput(ProcessBuilder.Redirect.DISCARD)
            .redirectError(ProcessBuilder.Redirect.DISCARD).start();
        try (OutputStream sink = process.getOutputStream()) {
            sink.write(bytes);
        }
        int status = process.waitFor();
        if (status != 0) throw new IOException(clipboard[0] + " exited " + status);
    }

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

    public static void main(String[] args) {
        try {
            if (args.length == 1 && "--desktop".equals(args[0])) {
                throw new UnsupportedOperationException("xcat JVM filesystem/clipboard bridge is not implemented");
            }
            XcatLauncher host=new XcatLauncher(args);
            int status=host.execute();
            if(status!=0){System.err.println("xcat JVM: WASI exited "+status);System.exit(status);}
            if(Arrays.asList(args).contains("--help")||Arrays.asList(args).contains("-h")){
                System.out.write(host.output.toByteArray());
                System.out.flush();
            }
            if(host.output.size()>0&&!Arrays.asList(args).contains("--help")&&!Arrays.asList(args).contains("-h")){
                copyToClipboard(host.output.toByteArray());
            }
        } catch (Throwable error) {
            System.err.println("xcat JVM host: " + error);
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }
}
