const std = @import("std");
const c = @cImport({
    @cInclude("curl/curl.h");
});

pub fn main() anyerror!void {
    var curl = c.curl_easy_init();
}
