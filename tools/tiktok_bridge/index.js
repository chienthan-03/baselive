const { TikTokLiveConnection } = require('tiktok-live-connector');

const username = process.argv[2];
if (!username) {
    console.error("Usage: node index.js <username>");
    process.exit(1);
}

// Create a new wrapper object and pass the username
const tiktokLiveConnection = new TikTokLiveConnection(username, {});

// Function to emit JSON event to stdout
function emitEvent(eventType, user, content, giftValue = null) {
    const event = {
        event_type: eventType,
        username: user,
        content: content,
        pts: Date.now() / 1000.0,
        gift_value: giftValue
    };
    console.log(JSON.stringify(event));
}

// Connect to the chat
tiktokLiveConnection.connect().then(state => {
    // We do not log info to stdout because Python expects pure JSON per line
    console.error(`Connected to roomId ${state.roomId}`);
}).catch(err => {
    console.error('Failed to connect', err);
    process.exit(1);
});

// Chat event
tiktokLiveConnection.on('chat', data => {
    emitEvent("COMMENT", data.user?.displayId || data.user?.nickname || "unknown", data.content);
});

// Gift event
tiktokLiveConnection.on('gift', data => {
    if (data.giftType === 1 && !data.repeatEnd) {
        // Streak in progress => wait for end
        return;
    }
    const cost = (data.diamondCount || 0) * (data.repeatCount || 1);
    const content = `sent ${data.giftName} x${data.repeatCount || 1}`;
    emitEvent("GIFT", data.user?.displayId || data.user?.nickname || "unknown", content, cost);
});

// Like event
tiktokLiveConnection.on('like', data => {
    const likeCount = data.likeCount || data.totalLikeCount || 1;
    emitEvent("LIKE", data.user?.displayId || data.user?.nickname || "unknown", `sent ${likeCount} likes`);
});

// Follow event
tiktokLiveConnection.on('follow', data => {
    emitEvent("FOLLOW", data.user?.displayId || data.user?.nickname || "unknown", "followed the host");
});

// Share event
tiktokLiveConnection.on('share', data => {
    emitEvent("SHARE", data.user?.displayId || data.user?.nickname || "unknown", "shared the stream");
});
