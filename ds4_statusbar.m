#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>

#include <stdio.h>
#include <string.h>

static NSDictionary *ds4_status_dictionary(NSData *data) {
	if (!data.length) return nil;
	NSError *error = nil;
	id value = [NSJSONSerialization JSONObjectWithData:data options:0 error:&error];
	if (error || ![value isKindOfClass:[NSDictionary class]]) return nil;
	NSDictionary *status = value;
	if (![[status objectForKey:@"active"] isKindOfClass:[NSNumber class]] ||
		![[status objectForKey:@"phase"] isKindOfClass:[NSString class]]) return nil;
	return status;
}

static double ds4_status_rate(NSDictionary *status, NSString *group) {
	id metrics = [status objectForKey:group];
	if (![metrics isKindOfClass:[NSDictionary class]]) return -1.0;
	id raw = [metrics objectForKey:@"avg_tps"];
	if (![raw isKindOfClass:[NSNumber class]]) return -1.0;
	double value = [raw doubleValue];
	return value > 0.0 ? value : -1.0;
}

static NSString *ds4_compact_rate(double rate) {
	if (rate <= 0.0) return @"—";
	if (rate >= 1000.0) return [NSString stringWithFormat:@"%.1fk", rate / 1000.0];
	if (rate >= 100.0) return [NSString stringWithFormat:@"%.0f", rate];
	return [NSString stringWithFormat:@"%.1f", rate];
}

static NSString *ds4_statusbar_title(NSDictionary *status) {
	if (!status) return @"DS4 离线";
	BOOL active = [[status objectForKey:@"active"] boolValue];
	NSString *phase = [status objectForKey:@"phase"];
	if (!active) return @"DS4 空闲";
	double prefill = ds4_status_rate(status, @"prefill");
	double decode = ds4_status_rate(status, @"decode");
	if ([phase isEqualToString:@"prefill"])
		return [NSString stringWithFormat:@"P %@", ds4_compact_rate(prefill)];
	if ([phase isEqualToString:@"decode"])
		return [NSString stringWithFormat:@"D %@ · P %@",
			ds4_compact_rate(decode), ds4_compact_rate(prefill)];
	return @"DS4 运行中";
}

static NSString *ds4_detailed_rate(double rate) {
	return rate > 0.0 ?
		[NSString stringWithFormat:@"%.1f t/s", rate] : @"—";
}

static long long ds4_status_count(NSDictionary *status, NSString *group,
								  NSString *key) {
	id metrics = [status objectForKey:group];
	if (![metrics isKindOfClass:[NSDictionary class]]) return -1;
	id raw = [metrics objectForKey:key];
	if (![raw isKindOfClass:[NSNumber class]]) return -1;
	long long value = [raw longLongValue];
	return value >= 0 ? value : -1;
}

static NSURL *ds4_dashboard_url(NSURL *status_url) {
	NSURLComponents *parts = [NSURLComponents componentsWithURL:status_url
											 resolvingAgainstBaseURL:NO];
	parts.path = @"/dashboard";
	parts.query = nil;
	parts.fragment = nil;
	return parts.URL;
}

@interface DS4StatusBarController : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) NSURL *statusURL;
@property(nonatomic, strong) NSURL *dashboardURL;
@property(nonatomic, strong) NSURLSession *session;
@property(nonatomic, strong) NSTimer *timer;
@property(nonatomic, strong) NSStatusItem *statusItem;
@property(nonatomic, strong) NSMenuItem *stateItem;
@property(nonatomic, strong) NSMenuItem *prefillItem;
@property(nonatomic, strong) NSMenuItem *decodeItem;
@property(nonatomic, strong) NSMenuItem *progressItem;
@property(nonatomic) BOOL requestInFlight;
- (instancetype)initWithStatusURL:(NSURL *)url;
@end

@implementation DS4StatusBarController

- (instancetype)initWithStatusURL:(NSURL *)url {
	self = [super init];
	if (self) {
		_statusURL = url;
		_dashboardURL = ds4_dashboard_url(url);
	}
	return self;
}

- (NSMenuItem *)informationalItem:(NSString *)title {
	NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:title action:nil
											 keyEquivalent:@""];
	item.enabled = NO;
	return item;
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
	(void)notification;
	self.statusItem = [[NSStatusBar systemStatusBar]
		statusItemWithLength:NSVariableStatusItemLength];
	NSStatusBarButton *button = self.statusItem.button;
	button.title = @"DS4 连接中";
	button.toolTip = @"DwarfStar 推理速度";
	button.font = [NSFont monospacedDigitSystemFontOfSize:[NSFont systemFontSize]
												 weight:NSFontWeightMedium];
	NSImage *image = [NSImage imageWithSystemSymbolName:@"bolt.horizontal.circle"
									 accessibilityDescription:@"DS4"];
	image.template = YES;
	button.image = image;
	button.imagePosition = NSImageLeading;

	NSMenu *menu = [[NSMenu alloc] initWithTitle:@"DS4"];
	self.stateItem = [self informationalItem:@"状态：连接中"];
	self.prefillItem = [self informationalItem:@"Prefill：—"];
	self.decodeItem = [self informationalItem:@"Decode：—"];
	self.progressItem = [self informationalItem:@"进度：—"];
	[menu addItem:self.stateItem];
	[menu addItem:self.prefillItem];
	[menu addItem:self.decodeItem];
	[menu addItem:self.progressItem];
	[menu addItem:[NSMenuItem separatorItem]];
	NSMenuItem *dashboard = [[NSMenuItem alloc] initWithTitle:@"打开 Dashboard"
		action:@selector(openDashboard:) keyEquivalent:@""];
	dashboard.target = self;
	[menu addItem:dashboard];
	NSMenuItem *refresh = [[NSMenuItem alloc] initWithTitle:@"立即刷新"
		action:@selector(refresh:) keyEquivalent:@"r"];
	refresh.target = self;
	[menu addItem:refresh];
	[menu addItem:[NSMenuItem separatorItem]];
	NSMenuItem *quit = [[NSMenuItem alloc] initWithTitle:@"退出 DS4 状态栏"
		action:@selector(terminate:) keyEquivalent:@"q"];
	quit.target = self;
	[menu addItem:quit];
	self.statusItem.menu = menu;

	NSURLSessionConfiguration *configuration =
		[NSURLSessionConfiguration ephemeralSessionConfiguration];
	configuration.requestCachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
	configuration.timeoutIntervalForRequest = 2.0;
	configuration.URLCache = nil;
	self.session = [NSURLSession sessionWithConfiguration:configuration];
	[self refresh:nil];
	self.timer = [NSTimer scheduledTimerWithTimeInterval:1.0 target:self
		selector:@selector(refresh:) userInfo:nil repeats:YES];
}

- (void)applicationWillTerminate:(NSNotification *)notification {
	(void)notification;
	[self.timer invalidate];
	[self.session invalidateAndCancel];
}

- (void)setOffline {
	self.statusItem.button.title = @"DS4 离线";
	self.statusItem.button.toolTip = @"无法读取 DS4 状态";
	self.stateItem.title = @"状态：离线";
	self.prefillItem.title = @"Prefill：—";
	self.decodeItem.title = @"Decode：—";
	self.progressItem.title = @"进度：—";
}

- (void)applyStatus:(NSDictionary *)status {
	NSString *title = ds4_statusbar_title(status);
	if ([title isEqualToString:@"DS4 离线"]) {
		[self setOffline];
		return;
	}
	BOOL active = [[status objectForKey:@"active"] boolValue];
	NSString *phase = [status objectForKey:@"phase"];
	double prefill = ds4_status_rate(status, @"prefill");
	double decode = ds4_status_rate(status, @"decode");
	self.statusItem.button.title = title;
	self.statusItem.button.toolTip = [NSString stringWithFormat:
		@"Decode %@ · Prefill %@", ds4_detailed_rate(decode),
		ds4_detailed_rate(prefill)];
	if (!active) {
		self.stateItem.title = @"状态：空闲";
		self.prefillItem.title = [NSString stringWithFormat:@"上次 Prefill：%@",
			ds4_detailed_rate(prefill)];
		self.decodeItem.title = [NSString stringWithFormat:@"上次 Decode：%@",
			ds4_detailed_rate(decode)];
		self.progressItem.title = @"进度：—";
		return;
	}
	self.stateItem.title = [phase isEqualToString:@"decode"] ?
		@"状态：解码中" : @"状态：预填充中";
	self.prefillItem.title = [NSString stringWithFormat:@"Prefill：%@",
		ds4_detailed_rate(prefill)];
	self.decodeItem.title = [NSString stringWithFormat:@"Decode：%@",
		[phase isEqualToString:@"decode"] ? ds4_detailed_rate(decode) : @"—"];
	NSString *group = [phase isEqualToString:@"decode"] ? @"decode" : @"prefill";
	NSString *current_key = [phase isEqualToString:@"decode"] ? @"generated" : @"current";
	NSString *total_key = [phase isEqualToString:@"decode"] ? @"max_tokens" : @"total";
	long long current = ds4_status_count(status, group, current_key);
	long long total = ds4_status_count(status, group, total_key);
	self.progressItem.title = current >= 0 && total > 0 ?
		[NSString stringWithFormat:@"进度：%lld / %lld token", current, total] :
		@"进度：—";
}

- (void)refresh:(id)sender {
	(void)sender;
	if (self.requestInFlight) return;
	self.requestInFlight = YES;
	NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:self.statusURL];
	request.HTTPMethod = @"GET";
	request.cachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
	request.timeoutInterval = 2.0;
	[request setValue:@"application/json" forHTTPHeaderField:@"Accept"];
	__weak typeof(self) weak_self = self;
	NSURLSessionDataTask *task = [self.session dataTaskWithRequest:request
		completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
			NSHTTPURLResponse *http = [response isKindOfClass:[NSHTTPURLResponse class]] ?
				(NSHTTPURLResponse *)response : nil;
			NSDictionary *status = !error && http.statusCode == 200 ?
				ds4_status_dictionary(data) : nil;
			dispatch_async(dispatch_get_main_queue(), ^{
				DS4StatusBarController *strong_self = weak_self;
				if (!strong_self) return;
				strong_self.requestInFlight = NO;
				[strong_self applyStatus:status];
			});
		}];
	[task resume];
}

- (void)openDashboard:(id)sender {
	(void)sender;
	if (self.dashboardURL) [[NSWorkspace sharedWorkspace] openURL:self.dashboardURL];
}

- (void)terminate:(id)sender {
	(void)sender;
	[NSApp terminate:nil];
}

@end

static void ds4_statusbar_usage(FILE *out) {
	fputs("usage: ds4-statusbar [--url STATUS_URL]\n"
		  "       ds4-statusbar --render-status\n\n"
		  "The default status URL is http://127.0.0.1:8077/ds4/status.\n"
		  "DS4_STATUS_URL provides the same override as --url.\n",
		  out);
}

static NSURL *ds4_status_url_from_arguments(int argc, const char **argv) {
	NSString *configured = [[[NSProcessInfo processInfo] environment]
		objectForKey:@"DS4_STATUS_URL"];
	if (!configured.length) configured = @"http://127.0.0.1:8077/ds4/status";
	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--url")) {
			if (++i >= argc) return nil;
			configured = [NSString stringWithUTF8String:argv[i]];
		} else if (strncmp(argv[i], "-psn_", 5)) {
			return nil;
		}
	}
	NSURL *url = [NSURL URLWithString:configured];
	NSString *scheme = url.scheme.lowercaseString;
	if (!url.host.length || (![scheme isEqualToString:@"http"] &&
		![scheme isEqualToString:@"https"])) return nil;
	return url;
}

int main(int argc, const char **argv) {
	@autoreleasepool {
		if (argc == 2 && !strcmp(argv[1], "--render-status")) {
			NSData *data = [[NSFileHandle fileHandleWithStandardInput] readDataToEndOfFile];
			NSString *title = ds4_statusbar_title(ds4_status_dictionary(data));
			printf("%s\n", title.UTF8String);
			return 0;
		}
		if (argc == 2 && (!strcmp(argv[1], "--help") || !strcmp(argv[1], "-h"))) {
			ds4_statusbar_usage(stdout);
			return 0;
		}
		NSURL *status_url = ds4_status_url_from_arguments(argc, argv);
		if (!status_url) {
			ds4_statusbar_usage(stderr);
			return 2;
		}
		NSApplication *application = [NSApplication sharedApplication];
		[application setActivationPolicy:NSApplicationActivationPolicyAccessory];
		DS4StatusBarController *controller =
			[[DS4StatusBarController alloc] initWithStatusURL:status_url];
		application.delegate = controller;
		[application run];
	}
	return 0;
}
