// SPDX-License-Identifier: Apache-2.0
// Experimental no_std WASI Preview 1 xcat backend. No Rust std or allocator.
#![no_std]
#![no_main]
use core::panic::PanicInfo;

// LLVM may lower slice comparisons to libc memcmp even in a no_std build.
// Provide the symbol locally so wasm2jar does not require an env.memcmp import.
// Volatile reads prevent LLVM from folding this implementation back into memcmp.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn memcmp(a:*const u8,b:*const u8,n:usize)->i32 {
    let mut i=0;
    while i<n {
        let x=unsafe{core::ptr::read_volatile(a.add(i))};
        let y=unsafe{core::ptr::read_volatile(b.add(i))};
        if x!=y{return x as i32-y as i32}
        i+=1;
    }
    0
}

#[panic_handler] fn panic(_: &PanicInfo) -> ! { loop {} }
#[repr(C)] struct Iovec { buf: *mut u8, len: u32 }
#[repr(C)] struct Ciovec { buf: *const u8, len: u32 }
#[link(wasm_import_module="wasi_snapshot_preview1")]
unsafe extern "C" {
    fn args_sizes_get(argc:*mut u32, size:*mut u32)->u32;
    fn args_get(argv:*mut *mut u8, buf:*mut u8)->u32;
    fn fd_readdir(fd:u32, buf:*mut u8, len:u32, cookie:u64, used:*mut u32)->u32;
    fn path_open(fd:u32, flags:u32, path:*const u8, len:u32, oflags:u32, rights:u64, inherited:u64, fdflags:u32, opened:*mut u32)->u32;
    fn fd_read(fd:u32, iovs:*const Iovec, n:u32, used:*mut u32)->u32;
    fn fd_write(fd:u32, iovs:*const Ciovec, n:u32, used:*mut u32)->u32;
    fn fd_close(fd:u32)->u32;
    fn proc_exit(status:u32)->!;
}
fn fail(msg:&[u8])->! { write(2,msg);unsafe{proc_exit(1)} }
fn write(fd:u32, data:&[u8]) {
    let mut at=0;
    while at<data.len() {
        let v=Ciovec{buf:data[at..].as_ptr(),len:(data.len()-at) as u32};
        let mut n=0;
        if unsafe{fd_write(fd,&v,1,&mut n)}!=0 || n==0 || n as usize>data.len()-at {unsafe{proc_exit(1)}}
        at+=n as usize;
    }
}
fn open(base:u32, name:&[u8], create:bool)->Result<u32,u32>{
    let mut fd=0;
    let status=unsafe{path_open(base,0,name.as_ptr(),name.len() as u32,if create {1}else{0},u64::MAX,u64::MAX,0,&mut fd)};
    if status==0 {Ok(fd)}else{Err(status)}
}
fn read(fd:u32, buf:&mut [u8])->Result<usize,()>{
    let v=Iovec{buf:buf.as_mut_ptr(),len:buf.len() as u32};
    let mut n=0;
    if unsafe{fd_read(fd,&v,1,&mut n)}!=0 || n as usize>buf.len(){Err(())}else{Ok(n as usize)}
}
const HELP:&[u8]=b"xcat -- filtered project files and optional task output to clipboard\nUsage: xcat [-d dir] [-f file] [-c config] [-e task|-r task] [-- task-arguments...]\n";
const DEFAULT_CONFIG:&[u8]=b"{\n  \"scanendfilter\": [\".bb\", \".bbclass\", \".c\", \".cc\", \".cmake\", \".cpp\", \".cxx\", \".go\", \".h\", \".hh\", \".hpp\", \".hxx\", \".in\", \".ini\", \".java\", \".jl\", \".json\", \".lua\", \".md\", \".py\", \".rc\", \".rs\", \".sh\", \".ps1\", \".sv\", \".tcl\", \".tex\", \".toml\", \".txt\", \".xml\", \".log\", \".yaml\", \".yml\"],\n  \"scanfullfilter\": [\"CMakeLists.txt\", \"Cargo.toml\", \"meson.build\", \"pom.xml\", \"Makefile\", \"makefile\", \"Justfile\"],\n  \"excludedirs\": [\".git\", \".svn\", \".hg\", \"target\", \"build\", \"node_modules\", \".venv\", \"venv\"],\n  \"max_file_bytes\": 2000000\n}\n";
fn eq_ignore_case(a:&[u8],b:&[u8])->bool{
    a.len()==b.len()&&a.iter().zip(b).all(|(x,y)|x.eq_ignore_ascii_case(y))
}
fn ends_ignore_case(a:&[u8],b:&[u8])->bool{
    a.len()>=b.len()&&eq_ignore_case(&a[a.len()-b.len()..],b)
}
// Configuration is held as UTF-8 JSON in a fixed buffer. A compact parser
// reads the three string arrays and the unsigned size limit without allocation.
struct Config<'a> {
    suffixes: &'a [u8], full: &'a [u8], excluded: &'a [u8], max:usize,
}
fn space(b:&[u8], mut i:usize)->usize {
    while i<b.len()&&b[i].is_ascii_whitespace(){i+=1}i
}
fn string_end(b:&[u8], i:usize)->Option<usize>{
    if b.get(i)!=Some(&b'"'){return None}
    let mut p=i+1;
    while p<b.len(){
        if b[p]==b'\\'{p+=2;continue}
        if b[p]==b'"'{return Some(p+1)}
        p+=1;
    }None
}
fn value_end(b:&[u8],i:usize)->Option<usize>{
    let i=space(b,i);
    match b.get(i)? {
        b'"'=>string_end(b,i),
        b'['|b'{'=>{
            let open=b[i];let close=if open==b'['{b']'}else{b'}'};
            let mut p=i+1;let mut depth=1usize;
            while p<b.len(){
                if b[p]==b'"'{p=string_end(b,p)?;continue}
                if b[p]==open{depth+=1}
                if b[p]==close{depth-=1;if depth==0{return Some(p+1)}}
                p+=1;
            }None
        },
        _=>{let mut p=i;while p<b.len()&&!matches!(b[p],b','|b'}'|b']'){p+=1}Some(p)}
    }
}
fn field<'a>(json:&'a [u8],key:&[u8])->Option<&'a [u8]>{
    let mut i=space(json,0);
    if json.get(i)!=Some(&b'{'){return None}
    i+=1;
    loop{
        i=space(json,i);
        if json.get(i)==Some(&b'}'){return None}
        let end=string_end(json,i)?;
        let name=&json[i+1..end-1];i=space(json,end);
        if json.get(i)!=Some(&b':'){return None}
        i=space(json,i+1);
        let v_end=value_end(json,i)?;
        if name==key{return Some(&json[i..v_end])}
        i=space(json,v_end);
        if json.get(i)!=Some(&b','){return None}
        i+=1;
    }
}
fn array_contains(json:&[u8],name:&[u8],suffix:bool)->bool{
    let mut i=space(json,0);
    if json.get(i)!=Some(&b'['){return false}
    i+=1;
    loop{
        i=space(json,i);
        if json.get(i)==Some(&b']'){return false}
        let Some(end)=string_end(json,i) else{return false};
        let entry=&json[i+1..end-1];
        if if suffix{ends_ignore_case(name,entry)}else{eq_ignore_case(name,entry)}{return true}
        i=space(json,end);
        if json.get(i)!=Some(&b','){return false}
        i+=1;
    }
}
fn config_from_json(json:&[u8])->Option<Config<'_>>{
    let suffixes=field(json,b"scanendfilter")?;
    let full=field(json,b"scanfullfilter")?;
    let excluded=field(json,b"excludedirs")?;
    let mut max_raw=field(json,b"max_file_bytes")?;
    while max_raw.last().is_some_and(|c|c.is_ascii_whitespace()) {max_raw=&max_raw[..max_raw.len()-1];}
    let mut max=0usize;
    if max_raw.is_empty(){return None}
    for &digit in max_raw {
        if !digit.is_ascii_digit(){return None}
        max=max.checked_mul(10)?.checked_add((digit-b'0') as usize)?;
    }
    if max==0{return None}
    Some(Config{suffixes,full,excluded,max})
}
fn allowed(name:&[u8],cfg:&Config<'_>)->bool{
    array_contains(cfg.full,name,false)||array_contains(cfg.suffixes,name,true)
}
fn excluded(name:&[u8],cfg:&Config<'_>)->bool{
    array_contains(cfg.excluded,name,false)
}
fn get_u32(bytes:&[u8])->u32{
    u32::from_le_bytes([bytes[0],bytes[1],bytes[2],bytes[3]])
}
fn get_u64(bytes:&[u8])->u64{
    u64::from_le_bytes([bytes[0],bytes[1],bytes[2],bytes[3],bytes[4],bytes[5],bytes[6],bytes[7]])
}
// The current Java WASI host exposes a 3/4/5 preopen for scan/config/report.
// Iteration uses one dirent at a time, so it does not need heap allocation.
// One shared staging buffer prevents a 2 MB stack frame at every directory depth.
// WASI Preview 1 execution is single-threaded in this launcher.
static mut FILE_BUFFER:[u8;2_000_001]=[0;2_000_001];
static mut FILE_COUNT:u32=0;
fn report_count() {
    let count=unsafe{FILE_COUNT};
    let mut digits=[0u8;10];let mut n=count;let mut at=digits.len();
    loop {at-=1;digits[at]=b'0'+(n%10) as u8;n/=10;if n==0{break}}
    write(2,b"XCAT_FILES:");write(2,&digits[at..]);write(2,b"\n");
}
fn emit_file(file:u32, path:&[u8],cfg:&Config<'_>) {
    let contents=unsafe{core::slice::from_raw_parts_mut(core::ptr::addr_of_mut!(FILE_BUFFER).cast::<u8>(),2_000_001)};
    let mut total=0usize;
    let mut ok=true;
    loop {
        if total==contents.len(){ok=false;break}
        match read(file,&mut contents[total..]) {
            Ok(0)=>break,
            Ok(n)=>total+=n,
            Err(_)=>{ok=false;break}
        }
    }
    unsafe{fd_close(file);}
    if ok&&total<=cfg.max&&!contents[..total].contains(&0)&&core::str::from_utf8(&contents[..total]).is_ok(){
        unsafe{FILE_COUNT=FILE_COUNT.saturating_add(1);}
        write(1,b"===== ./");write(1,path);write(1,b" =====\n");
        write(1,&contents[..total]);
        if !contents[..total].ends_with(b"\n"){write(1,b"\n")}
        write(1,b"\n");
    }
}
fn scan(fd:u32, prefix:&[u8], depth:u32,cfg:&Config<'_>) {
    if depth>24 {return}
    let mut cookie=0u64;
    let mut entries=[0u8;8192];
    let mut path=[0u8;4096];
    loop {
        let mut used=0;
        if unsafe{fd_readdir(fd,entries.as_mut_ptr(),entries.len() as u32,cookie,&mut used)}!=0 {fail(b"xcat: readdir failed\n")}
        if used==0 {break}
        let mut at=0;
        while at+24<=used as usize {
            let next=get_u64(&entries[at..at+8]);
            let n=get_u32(&entries[at+16..at+20]) as usize;
            let kind=entries[at+20];
            if at+24+n>used as usize {fail(b"xcat: truncated dirent\n")}
            let name=&entries[at+24..at+24+n];
            if name!=b"."&&name!=b".."&&!excluded(name,cfg)&&prefix.len()+n+1<path.len() {
                path[..prefix.len()].copy_from_slice(prefix);
                path[prefix.len()..prefix.len()+n].copy_from_slice(name);
                let len=prefix.len()+n;
                if kind==3 {
                    if let Ok(child)=open(3,&path[..len],false) {
                        path[len]=b'/';
                        scan(child,&path[..len+1],depth+1,cfg);
                        unsafe{fd_close(child);}
                    }
                }else if kind==4&&allowed(name,cfg){
                    if let Ok(file)=open(3,&path[..len],false){
                        emit_file(file,&path[..len],cfg);
                    }
                }
            }
            at+=24+n;
            cookie=next;
        }
        // A partial dirent cannot be recovered safely with this host's
        // cookie implementation; reject instead of silently dropping files.
        if at!=used as usize {fail(b"xcat: incomplete dirent\n")}
    }
}
fn print_report(args:&[&[u8]]) {
    if args.len()!=5 {fail(b"xcat: invalid task report arguments\n")}
    write(1,b"\n===== EXECUTABLE OUTPUT: ");write(1,args[1]);write(1,b" =====\n");
    for (label,name) in [(b"===== STDOUT =====\n".as_slice(),b"stdout".as_slice()),
                         (b"===== STDERR =====\n".as_slice(),b"stderr".as_slice())] {
        write(1,label);
        let fd=open(5,name,false).unwrap_or_else(|_|fail(b"xcat: missing task output\n"));
        let mut buf=[0u8;8192];
        let mut last=b'\n';
        loop {
            let n=read(fd,&mut buf).unwrap_or_else(|_|fail(b"xcat: task read failed\n"));
            if n==0 {break}
            // Lossy UTF-8 conversion is handled by the Java host's task
            // runner for now; regular UTF-8 output is copied unchanged.
            last=buf[n-1];write(1,&buf[..n]);
        }
        unsafe{fd_close(fd);}
        if last!=b'\n' {write(1,b"\n")}
    }
    write(1,b"===== EXIT STATUS: ");write(1,args[4]);write(1,b" =====\n");
}
#[unsafe(no_mangle)]
pub extern "C" fn _start(){
    let mut argc=0;let mut size=0;
    if unsafe{args_sizes_get(&mut argc,&mut size)}!=0||argc==0||argc>32||size>4096{fail(b"xcat: invalid arguments\n")}
    let mut argv=[core::ptr::null_mut::<u8>();32];
    let mut argbuf=[0u8;4096];
    if unsafe{args_get(argv.as_mut_ptr(),argbuf.as_mut_ptr())}!=0{fail(b"xcat: args_get failed\n")}
    let mut args=[b"".as_slice();32];
    for j in 0..argc as usize {
        let ptr=argv[j];let offset=unsafe{ptr.offset_from(argbuf.as_ptr())};
        if offset<0||offset as usize>=argbuf.len(){fail(b"xcat: invalid argument pointer\n")}
        let value=&argbuf[offset as usize..];
        let end=value.iter().position(|b|*b==0).unwrap_or(value.len());
        args[j]=&value[..end];
    }
    if argc>1 && args[1]==b"--wasm-task-report" {
        print_report(&args[1..argc as usize]);return
    }
    let mut i=1usize;
    let mut cfg:&[u8]=b"config.json";
    let mut selected:Option<&[u8]>=None;
    while i<argc as usize{
        let ptr=argv[i];
        let offset=unsafe{ptr.offset_from(argbuf.as_ptr())};
        if offset<0||offset as usize>=argbuf.len(){fail(b"xcat: invalid argument pointer\n")}
        let arg=&argbuf[offset as usize..];
        let end=arg.iter().position(|b|*b==0).unwrap_or(arg.len());
        let a=&arg[..end];
        if a==b"-h"||a==b"--help"{write(1,HELP);return}
        if a==b"-d"||a==b"--dir"||a==b"-c"||a==b"--config"||a==b"-f"||a==b"--file"{
            i+=1;if i>=argc as usize{fail(b"xcat: missing option value\n")}
            if a==b"-c"||a==b"--config"{
                let ptr=argv[i];let offset=unsafe{ptr.offset_from(argbuf.as_ptr())};
                if offset<0||offset as usize>=argbuf.len(){fail(b"xcat: invalid config pointer\n")}
                let value=&argbuf[offset as usize..];
                let end=value.iter().position(|b|*b==0).unwrap_or(value.len());
                cfg=&value[..end];
            }else if a==b"-f"||a==b"--file"{
                if selected.is_some(){fail(b"xcat: multiple -f files\n")}
                let ptr=argv[i];let offset=unsafe{ptr.offset_from(argbuf.as_ptr())};
                if offset<0||offset as usize>=argbuf.len(){fail(b"xcat: invalid file pointer\n")}
                let value=&argbuf[offset as usize..];
                let end=value.iter().position(|b|*b==0).unwrap_or(value.len());
                selected=Some(&value[..end]);
            }
        }else{fail(b"xcat: unsupported argument\n")}
        i+=1;
    }
    // The Java host mounts the configuration parent at /cfg.
    let config_name=cfg.strip_prefix(b"/cfg/").unwrap_or(cfg);
    // Create defaults only for a missing config; do not clobber user settings.
    let mut config_fd=0;
    let created=unsafe{path_open(4,0,config_name.as_ptr(),config_name.len() as u32,5,u64::MAX,u64::MAX,0,&mut config_fd)};
    if created==0 {write(config_fd,DEFAULT_CONFIG);unsafe{fd_close(config_fd);}}
    else if let Ok(fd)=open(4,config_name,false){unsafe{fd_close(fd);}}
    else {fail(b"xcat: cannot open config\n")}
    let fd=open(4,config_name,false).unwrap_or_else(|_|fail(b"xcat: cannot read config\n"));
    let mut config_buf=[0u8;65536];
    let mut used=0usize;
    loop {
        if used==config_buf.len(){fail(b"xcat: configuration too large\n")}
        let n=read(fd,&mut config_buf[used..]).unwrap_or_else(|_|fail(b"xcat: config read failed\n"));
        if n==0{break}
        used+=n;
    }
    unsafe{fd_close(fd);}
    let cfg=config_from_json(&config_buf[..used]).unwrap_or_else(||fail(b"xcat: invalid config\n"));
    if let Some(file)=selected {
        // Explicit file names bypass suffix and excluded-directory filters.
        // The host mounts the selected file's parent at fd 3.
        let basename=file.rsplit(|b|*b==b'/').next().unwrap_or(file);
        if basename.is_empty(){fail(b"xcat: invalid file path\n")}
        let fd=open(3,file,false).unwrap_or_else(|_|fail(b"xcat: cannot open selected file\n"));
        emit_file(fd,basename,&cfg);
    }else{
        scan(3,b"",0,&cfg);
    }
    report_count();
}
