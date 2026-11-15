"""HLD case studies and LLD decisions; diagram hand-offs preserve Studio scenarios."""

from .content import lesson, track

DESIGN = track(
    "system-design-cases",
    "system_design",
    "System design: HLD and LLD case studies",
    "Nine bounded design cases. Objective checks are not an assessment of a full design explanation.",
    (
        lesson(
            "sd-capacity",
            "HLD: capacity and bottlenecks",
            ("cs-architecture",),
            (
                "Translate daily traffic into average request rate.",
                "Separate average load from peak and per-component capacity.",
            ),
            "High-level design begins with requirements and explicit workload assumptions. Average request rate is daily requests divided by seconds per day, but peak traffic can be much higher. Capacity estimates should name the service, payload size and concurrency. A single average does not prove resilience or a latency objective.",
            "A service receives 8,640,000 requests per day. Dividing by 86,400 seconds gives 100 requests/second on average. If the stated peak is five times average, provision and test for 500 requests/second before adding safety margin.",
            (
                "Convert days to seconds.",
                "Use 86,400 seconds per day.",
                "8,640,000 divided by 86,400 is 100.",
            ),
            "What is the average rate for 8,640,000 requests per day?",
            ("10 requests/s", "100 requests/s", "500 requests/s", "1000 requests/s"),
            "100 requests/s",
            "The daily total divided by 86,400 gives 100 per second; the stated peak is a separate 500 per second assumption.",
        ),
        lesson(
            "sd-url-shortener",
            "HLD: durable URL mappings",
            ("sd-capacity", "cs-indexes"),
            (
                "Separate durable mapping from cached lookup.",
                "Choose collision handling for short identifiers.",
            ),
            "A URL shortener stores a durable mapping from short key to destination and serves read-heavy redirects through a cache. A random key is not automatically unique: enforce uniqueness in storage and retry collisions. Expiration and revocation require invalidation semantics so a stale cache does not redirect a removed mapping indefinitely.",
            "If two creators both propose key abc, a unique database constraint permits only one insertion. The other retries a new key. The redirect service resolves committed mappings; a cache miss loads the authoritative row rather than manufacturing a destination.",
            (
                "Random generation can collide.",
                "The persistent mapping must enforce the invariant.",
                "Use a unique key constraint and retry the collision.",
            ),
            "What reliably prevents two destinations from sharing one committed short key?",
            (
                "A unique database constraint with collision retry",
                "Randomness alone",
                "A larger browser cache",
                "Returning success before storing",
            ),
            "A unique database constraint with collision retry",
            "Storage uniqueness resolves concurrent collisions; probability alone cannot enforce the one-key-one-mapping invariant.",
            difficulty="intermediate",
            minutes=25,
            target="/studio?scenario=SD-CORE-03",
        ),
        lesson(
            "sd-webhook",
            "HLD: reliable webhook delivery",
            ("cs-http", "sd-capacity"),
            (
                "Acknowledge only durable acceptance.",
                "Pair retries with receiver deduplication.",
            ),
            "Webhook delivery separates durable event acceptance from later network attempts. A queue supports retry after transient failures, but a lost receiver response creates uncertainty about whether the effect happened. At-least-once delivery therefore needs a stable event identifier and receiver-side deduplication; it does not imply exactly-once side effects.",
            "The sender persists event E, sends it, and the receiver commits E but its response is lost. A retry carries the same E. The receiver checks its processed-event record and returns the prior result instead of applying the side effect twice.",
            (
                "A lost response can follow a committed receiver effect.",
                "The retry must retain the original event identity.",
                "Deduplicate E at the receiver transaction boundary.",
            ),
            "What prevents duplicate receiver side effects when event E is retried?",
            (
                "Receiver-side deduplication using stable E",
                "A new ID on every retry",
                "Retries alone",
                "Only a longer timeout",
            ),
            "Receiver-side deduplication using stable E",
            "The stable identifier ties retries to one logical event; receiver-side atomic deduplication protects the business effect.",
            difficulty="intermediate",
            minutes=25,
            target="/studio?scenario=SD-CORE-02",
        ),
        lesson(
            "sd-notification",
            "HLD: fan-out and provider backpressure",
            ("sd-webhook",),
            (
                "Bound queue work and retry budgets.",
                "Respect per-provider capacity and recipient preferences.",
            ),
            "Notification fan-out expands one event into many recipient deliveries. Durable jobs separate acceptance from provider capacity, and bounded workers respect provider limits. Retry budgets and dead-letter handling prevent a failing provider from consuming all capacity. Recipient preferences need a defined check time rather than being assumed permanent.",
            "A burst creates 1000 messages for a provider limited to 50 sends/second. Ignoring all other overhead, draining requires at least 20 seconds. Adding unlimited workers does not increase the provider limit and may instead cause throttling and retries.",
            (
                "The provider, not worker count, defines this ceiling.",
                "Divide queued sends by permitted sends per second.",
                "1000/50 is 20 seconds.",
            ),
            "Ignoring overhead, a 50 sends/s provider needs at least how long for 1000 sends?",
            ("2 seconds", "10 seconds", "20 seconds", "50 seconds"),
            "20 seconds",
            "The throughput lower bound is 1000 divided by 50, so at least 20 seconds before overhead or retries.",
            difficulty="intermediate",
            minutes=25,
            target="/studio?scenario=SD-CORE-04",
        ),
        lesson(
            "sd-autocomplete",
            "HLD: prefix search and ranked candidates",
            ("cs-indexes", "sd-capacity"),
            (
                "Choose a prefix representation.",
                "Separate candidate lookup from freshness and ranking.",
            ),
            "Autocomplete retrieves a small ranked set for a prefix under a latency budget. A trie or ordered prefix index narrows candidates, while cached top-k suggestions trade memory for read speed. Ranking updates and privacy-sensitive inputs require explicit freshness and retention policies. Prefix lookup alone does not solve relevance or abuse.",
            "For stored terms car, cart and cat, prefix ca admits all three while prefix car admits only car and cart. A top-k list attached to a prefix node avoids scanning every descendant during each request but must be updated when ranks change.",
            (
                "Filter by characters from the start.",
                "cat shares ca but not car.",
                "Only car and cart begin with car.",
            ),
            "Which candidates match prefix car among car, cart and cat?",
            ("car and cart", "cart and cat", "All three", "Only cat"),
            "car and cart",
            "Prefix membership compares the leading characters; cat differs at the third character.",
            difficulty="intermediate",
            minutes=25,
            target="/studio?scenario=SD-CORE-05",
        ),
        lesson(
            "sd-lru",
            "LLD: LRU cache composition",
            ("dsa-hashing", "dsa-linked-list"),
            (
                "Compose lookup and recency structures.",
                "Define which operations refresh recency.",
            ),
            "A least-recently-used cache can combine a hash map for key lookup with a doubly linked list for recency order. A successful get moves its entry to the most-recent end; insertion beyond capacity removes the least-recent end. Define updates, missing keys and capacity zero explicitly before implementing pointer changes.",
            "Capacity is 2. Put A, put B, get A, then put C. The get makes A more recent than B, so inserting C evicts B. A FIFO queue would incorrectly evict A because insertion order is not access recency.",
            (
                "A successful get updates recency.",
                "After get A, B is least recently used.",
                "Evict B when C exceeds capacity.",
            ),
            "Which key is evicted in the capacity-2 sequence put A, put B, get A, put C?",
            ("A", "B", "C", "None"),
            "B",
            "Accessing A refreshes its recency, leaving B least recent when C arrives.",
            difficulty="intermediate",
            minutes=25,
        ),
        lesson(
            "sd-parking",
            "LLD: parking allocation invariants",
            ("cs-oop", "cs-transactions"),
            (
                "Model state transitions and capacity.",
                "Make check-and-allocate atomic under concurrency.",
            ),
            "A parking model can separate Vehicle, Spot, Ticket and AllocationPolicy responsibilities. The critical invariant is that one spot has at most one active allocation. Checking availability and assigning a ticket must be one atomic transition; otherwise two arrivals can both observe the final free spot and occupy it.",
            "Spot S is free. Requests A and B both read free before either writes. Without an atomic allocation guard, both issue active tickets for S. A transaction or compare-and-set from free to occupied lets exactly one succeed and the other retry.",
            (
                "Two reads can both see the same old state.",
                "The check and claim must be indivisible.",
                "Guard the free-to-occupied transition atomically.",
            ),
            "Which operation protects the one-active-ticket-per-spot invariant?",
            (
                "Atomic check-and-allocate",
                "Checking then writing without a guard",
                "Printing the spot twice",
                "Only changing the ticket color",
            ),
            "Atomic check-and-allocate",
            "The availability test and assignment must serialize to prevent concurrent double allocation.",
            difficulty="intermediate",
            minutes=25,
        ),
        lesson(
            "sd-observer",
            "LLD: observer subscriptions and lifecycle",
            ("cs-solid",),
            (
                "Separate publisher policy from subscriber callbacks.",
                "Define unsubscribe and failure semantics.",
            ),
            "The observer pattern lets a publisher notify registered subscribers without hardcoding their concrete classes. A subscription needs a lifecycle: duplicate registration, unsubscription, callback failures and notifications during removal require defined behavior. Snapshotting the subscriber collection avoids iteration corruption when callbacks change subscriptions.",
            "A publisher snapshots listeners A and B for one event. A unsubscribes B during its callback. Under snapshot semantics B still receives this event but not the next one; that behavior should be part of the contract rather than an accidental list-iteration effect.",
            (
                "The current dispatch has already captured its recipients.",
                "Changes affect the next snapshot.",
                "B receives the current event only under this stated contract.",
            ),
            "Under the stated snapshot contract, what happens when A unsubscribes B during dispatch?",
            (
                "B receives this event but not the next",
                "B receives every future event",
                "The publisher must crash",
                "All listeners are deleted",
            ),
            "B receives this event but not the next",
            "The current immutable snapshot includes B; the next dispatch snapshots the updated subscription set.",
            difficulty="intermediate",
            minutes=20,
        ),
        lesson(
            "sd-elevator",
            "LLD: elevator states and safety transitions",
            ("cs-oop", "apt-arrangement"),
            (
                "Represent explicit operational states.",
                "Check safety guards before motion transitions.",
            ),
            "An elevator controller can model idle, moving and door-open states with guarded transitions. Request scheduling decides service order, but safety rules constrain every schedule: motion must not begin while a door is open. Encoding guards in the transition boundary is stronger than hoping each caller remembers a boolean check.",
            "At floor 2 with the door open, a request for floor 5 is queued. The controller closes and confirms the door interlock before entering moving-up state. The scheduling preference cannot bypass that safety transition.",
            (
                "Separate choosing a destination from authorizing movement.",
                "The door interlock constrains every schedule.",
                "Confirm closed doors before entering a moving state.",
            ),
            "What guard must hold before entering a moving state in this model?",
            (
                "Doors confirmed closed",
                "Queue length is odd",
                "Destination is even",
                "A log file exists",
            ),
            "Doors confirmed closed",
            "The explicit safety invariant disallows movement with an open door regardless of request order.",
            difficulty="intermediate",
            minutes=25,
        ),
    ),
)

ADDITIONAL_CASES = (
    lesson(
        "sd-chat",
        "HLD: chat delivery, ordering and reconnect",
        ("sd-webhook", "cs-consistency"),
        (
            "Define durable acceptance versus recipient delivery.",
            "Scope ordering and reconnect semantics.",
        ),
        "Design a one-to-one chat service with offline recipients and reconnecting clients. Persist a message before acknowledging durable acceptance, assign a stable message identifier and specify ordering per conversation rather than globally. Live delivery uses connection routing; offline delivery and reconnect rely on durable history and cursors. Transport reconnects can duplicate sends.",
        "A sender submits message M, the service persists it, but the acknowledgement is lost. The sender retries the same M identifier. A uniqueness guard returns the existing record; the recipient resumes after cursor 41 and reads committed message 42 once in its displayed history.",
        (
            "A lost acknowledgement may follow a committed message.",
            "Retain message identity across the retry.",
            "Deduplicate that identity at durable acceptance.",
        ),
        "What protects durable chat history from duplicate insertion after retrying M?",
        (
            "A stable message ID with uniqueness enforcement",
            "A new ID for each retry",
            "Only a longer socket timeout",
            "Sending without persistence",
        ),
        "A stable message ID with uniqueness enforcement",
        "A repeated logical message resolves to its existing committed record, rather than creating another history item.",
        difficulty="advanced",
        minutes=30,
    ),
    lesson(
        "sd-rate-limiter",
        "HLD/LLD: token buckets and distributed quotas",
        ("sd-capacity", "cs-isolation"),
        (
            "Model refill, burst capacity and atomic consumption.",
            "Define fail-open or fail-closed behavior explicitly.",
        ),
        "Design a per-tenant API limiter using a token bucket: refill at a configured rate up to a bounded capacity, and consume tokens atomically for admitted requests. Capacity allows bursts while refill controls sustained load. Multiple server replicas need a shared authoritative operation or a documented approximate quota; unsynchronized local buckets multiply the allowed total.",
        "A bucket has capacity 5, refill 2 tokens/second and starts full. Five simultaneous unit-cost requests can pass immediately; a sixth must wait or be rejected. After one second, at most two consumed tokens are replenished, still capped at capacity.",
        (
            "The bucket starts with exactly five tokens.",
            "Each admitted request consumes one.",
            "No refill occurs during the simultaneous burst.",
        ),
        "How many unit-cost requests can pass immediately from that full bucket?",
        ("2", "5", "7", "Unlimited"),
        "5",
        "Immediate admission is bounded by the initial five tokens; refill does not create tokens before time elapses.",
        difficulty="advanced",
        minutes=30,
    ),
    lesson(
        "sd-file-storage",
        "HLD: object storage and upload finalization",
        ("cs-transactions", "cs-tls"),
        (
            "Separate uploaded bytes from committed file metadata.",
            "Validate integrity and ownership before making an object visible.",
        ),
        "Design file storage supporting large resumable uploads. Store bounded chunks under an owned upload identifier, verify their hashes, then atomically finalize an immutable object manifest. Bytes alone do not prove a completed file: missing chunks, wrong ownership or a failed manifest commit must prevent publication. Downloads require scoped authorization and integrity checks.",
        "An upload declares three chunks but only chunks 0 and 2 are present. Even if those hashes match, finalization must reject the incomplete manifest because chunk 1 is missing. The client can resume that chunk instead of exposing a truncated file as complete.",
        (
            "Finalization must account for every declared chunk.",
            "Hashes of present chunks do not fill a missing position.",
            "Reject publication until chunk 1 is verified.",
        ),
        "Should a declared three-chunk file be published with only chunks 0 and 2 verified?",
        (
            "No",
            "Yes if either chunk is large",
            "Yes after a timeout",
            "Only if the filename is short",
        ),
        "No",
        "The committed manifest requires all declared chunks; verified partial bytes cannot establish complete-file integrity.",
        difficulty="advanced",
        minutes=30,
    ),
    lesson(
        "sd-news-feed",
        "HLD: news-feed fan-out and ranking",
        ("sd-notification", "cs-indexes"),
        (
            "Compare fan-out-on-write with fan-out-on-read.",
            "Handle high-follower authors without unbounded synchronous work.",
        ),
        "Design a news feed with follows, privacy changes and ranked pagination. Fan-out-on-write precomputes recipient entries for fast reads but a celebrity post can create enormous work. Fan-out-on-read avoids that write burst but increases read aggregation. A hybrid can push ordinary posts and pull high-follower authors, while ranking and cursor stability need explicit semantics.",
        "An ordinary author has 100 followers and a celebrity has 10 million. Pushing every celebrity post to all feeds creates 10 million recipient writes. Keeping celebrity posts in an author timeline and merging them at read time avoids that particular write explosion.",
        (
            "Identify the operation multiplied by follower count.",
            "The celebrity has ten million recipients.",
            "Pulling celebrity posts avoids materializing every recipient write.",
        ),
        "Which hybrid choice avoids ten million feed writes for each celebrity post?",
        (
            "Pull celebrity posts during feed reads",
            "Synchronously push to all followers",
            "Remove all pagination",
            "Duplicate the post ten million times first",
        ),
        "Pull celebrity posts during feed reads",
        "Pulling trades read aggregation for avoiding that enormous fan-out-on-write workload.",
        difficulty="advanced",
        minutes=30,
    ),
    lesson(
        "sd-video-streaming",
        "HLD: video pipelines and adaptive delivery",
        ("sd-file-storage", "sd-capacity"),
        (
            "Separate upload/transcode from playback delivery.",
            "Choose a bitrate compatible with measured throughput.",
        ),
        "Design on-demand video streaming using durable originals, asynchronous transcoding, segment manifests and CDN delivery. Adaptive bitrate playback chooses among encoded variants based on throughput and buffer state. A high-resolution label does not guarantee smooth playback: sustained bitrate must fit network capacity with headroom. Transcode retries need stable job identity and publication only after output validation.",
        "Available variants use 1, 3 and 6 Mbps. With sustained client throughput 4 Mbps and a stated 20% headroom budget, the usable limit is 3.2 Mbps. The 3 Mbps variant fits; 6 Mbps would consume buffer faster than the network refills it.",
        (
            "Apply the headroom to measured throughput.",
            "4*0.8 leaves 3.2 Mbps.",
            "Choose the highest listed bitrate no greater than 3.2.",
        ),
        "Which listed variant fits that stated throughput budget?",
        ("1 Mbps only", "3 Mbps", "6 Mbps", "All variants equally"),
        "3 Mbps",
        "The allowed rate is 3.2 Mbps, so three is the highest available variant that fits the budget.",
        difficulty="advanced",
        minutes=30,
    ),
    lesson(
        "sd-ticket-booking",
        "HLD/LLD: seat holds and purchase state",
        ("sd-parking", "sd-webhook"),
        (
            "Model held, paid, expired and released states.",
            "Prevent two active owners for a seat across retries.",
        ),
        "Design ticket booking with temporary seat holds and payment uncertainty. A hold needs an expiry and atomic seat claim; payment completion must reference that owned hold and transition through a guarded state machine. A lost payment response is not proof of failure. Stable payment identifiers and reconciliation prevent both duplicate charges and releasing a seat whose successful payment is still being confirmed.",
        "Two clients request the last seat. An atomic free-to-held transition lets only one acquire it. If payment succeeds but the response is lost, a retry with the same payment key resolves the prior operation rather than charging again or assigning the seat to a second client.",
        (
            "Separate seat allocation from network-response arrival.",
            "Only one atomic claim can own the free seat.",
            "Payment retry must preserve the original identity.",
        ),
        "What enforces one active hold on the last available seat?",
        (
            "Atomic free-to-held transition",
            "Two independent availability reads",
            "Client-generated success flags",
            "Only hiding the button",
        ),
        "Atomic free-to-held transition",
        "The storage transition serializes competing claims; presentation changes and unguarded reads cannot enforce unique ownership.",
        difficulty="advanced",
        minutes=30,
    ),
)

# Each requested case adds its own evolving requirements and unassessed review criteria.
CASE_DETAILS = {
    "sd-url-shortener": (
        "Case prompt: create and resolve short links with durable uniqueness and bounded redirect latency. Evolution: add custom aliases, expiry, revocation and multiple regions. Trade-offs: random identifiers versus allocated IDs; authoritative reads versus cache staleness; global uniqueness versus partition availability.",
        (
            "Define collision and alias ownership handling.",
            "Explain revocation propagation to caches.",
            "State the regional consistency and failure policy.",
        ),
    ),
    "sd-chat": (
        "Evolution: add group conversations, offline devices and multi-device read receipts. Trade-offs: conversation ordering versus global ordering; durable acknowledgement versus live delivery latency; presence accuracy versus partition availability. Bound reconnect history and define duplicate display semantics.",
        (
            "Specify message acceptance and ordering scope.",
            "Explain reconnect cursors and deduplication.",
            "Model offline devices and group fan-out.",
        ),
    ),
    "sd-notification": (
        "Case prompt: deliver user notifications over email and push with preference checks. Evolution: add large campaigns, per-provider limits and late opt-outs. Trade-offs: immediate fan-out versus queued latency; retry depth versus provider cost; captured preferences versus send-time revalidation.",
        (
            "Separate durable acceptance from delivery.",
            "Bound fan-out and provider retries.",
            "Explain how opt-outs affect queued jobs.",
        ),
    ),
    "sd-rate-limiter": (
        "Evolution: add paid-tier bursts, geographically distributed replicas and limiter-store failure. Trade-offs: exact shared quotas versus local approximation; availability versus fail-closed protection; fairness versus throughput. Include trusted clocks and atomic refill/consume in the LLD.",
        (
            "Derive burst and sustained-rate behavior.",
            "Describe atomic distributed consumption.",
            "Choose and justify a limiter-failure policy.",
        ),
    ),
    "sd-file-storage": (
        "Evolution: add deduplication, versioned files, malware scanning and cross-region durability. Trade-offs: content addressing versus privacy leakage; immutable blobs versus mutable metadata; early upload acknowledgement versus publication integrity. State cleanup rules for abandoned uploads.",
        (
            "Verify complete manifests and ownership.",
            "Separate upload acceptance from publication.",
            "Explain durability, scanning and orphan cleanup.",
        ),
    ),
    "sd-news-feed": (
        "Evolution: add celebrity accounts, blocked users and cursor-stable ranked pagination. Trade-offs: push versus pull fan-out; fresh ranking versus stable pages; precomputed entries versus privacy revocation cost. Describe a bounded candidate-generation stage and a ranking stage separately.",
        (
            "Choose fan-out policies by workload.",
            "State pagination and ranking freshness semantics.",
            "Enforce privacy changes on cached candidates.",
        ),
    ),
    "sd-video-streaming": (
        "Evolution: add multiple codecs, regional CDN failures and live events. Trade-offs: encoding/storage cost versus bandwidth; segment length versus latency; failover resilience versus stale manifests. Model idempotent transcoding and only publish validated playable variants.",
        (
            "Separate transcoding and playback boundaries.",
            "Budget bitrate and buffering explicitly.",
            "Explain variant publication and CDN failure recovery.",
        ),
    ),
    "sd-ticket-booking": (
        "Evolution: add flash-sale bursts, payment webhooks and expired-hold races. Trade-offs: temporary reservation duration versus inventory utilization; synchronous payment decisions versus reconciliation; fair admission versus availability. Model seat, hold, order and payment identities independently.",
        (
            "Guard seat and hold state transitions.",
            "Explain payment uncertainty and deduplication.",
            "Resolve expiry-versus-payment races without double allocation.",
        ),
    ),
}
DESIGN = {
    **DESIGN,
    "description": "Fifteen lessons include all eight requested HLD case studies plus LLD cache, parking, observer, elevator and quota/booking state models.",
    "lessons": [
        (
            {
                **entry,
                "explanation": entry["explanation"]
                + "\n\n"
                + CASE_DETAILS[entry["id"]][0],
                "explanation_rubric": {
                    **entry["explanation_rubric"],
                    "criteria": list(CASE_DETAILS[entry["id"]][1]),
                },
            }
            if entry["id"] in CASE_DETAILS
            else entry
        )
        for entry in DESIGN["lessons"] + list(ADDITIONAL_CASES)
    ],
}
