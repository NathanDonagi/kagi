## Inspiration

In early 2024, an employee at a multinational firm in Hong Kong joined a video call with their CFO and several colleagues and wired out **$25 million**. Every other person on that call was a deepfake. That story stuck with us. AI deepfakes are making it harder every month to know who you're actually talking to, and "I recognize their face and voice" is no longer proof of anything.

At the same time, the internet is filling up with age restrictions. A recent ruling said Meta must limit Instagram Reels for users under 16. Sites have stopped operating in places like Georgia and the UK rather than deal with age verification laws. Discord started requiring full government IDs to prove users were old enough, and those IDs were later exposed in a breach. We're worried that age checks are becoming an excuse to kill privacy and anonymity online. **Kagi is our attempt to take that excuse away.** It lets you prove you're over 18 without showing anyone your ID.

The third problem is bots. Twitter and Threads are both full of them (Twitter much worse, but both are rampant). A platform can't fix that without knowing that each account belongs to a unique real person. Today that means handing over your identity.

So we asked: **can one physical key prove who you are, how old you are, and that you're a unique human, while revealing nothing else?**

## What it does

Kagi is a physical key issued by a trusted authority. It is cryptographically bound to facts about you (name, date of birth, SSN), but it never stores those facts. It only answers **yes or no** to specific questions:

- **"Is this really Nathan Donagi?"** A video call host sends a code, the other person taps their key, and the host sees *Verified* or *Not verified*. A deepfake has no key.
- **"Are you over 18?"** A site like our demo *Blindgram* (an Instagram-style app with 18+ Reels) learns only "yes". It gets no name, no birthday and no ID photo to leak.
- **"Is this a new person?"** At sign-up the site learns only whether this person already has an account. It never learns who they are, so one person gets one account, and bot farms can't sign up thousands of them.

## How we built it

The key holds salted **commitments**, not facts. For each fact, the authority computes

$$
C = \text{PBKDF2-HMAC-SHA256}\big(\text{SHA256}(\text{parts}),\ \text{salt},\ 200\big)
$$

where the name, date of birth, SSN and PIN are chained into `parts`, so the high-value facts can't be guessed on their own. Age thresholds you *don't* meet are filled with random bytes, so an "over 21" slot on a 19-year-old's key looks exactly like a real one:

$$
C_{\text{over }T} = \begin{cases} \text{commit}(["\text{OVER}", T]) & \text{age} \ge T \\ \text{random bytes} & \text{otherwise} \end{cases}
$$

When the key answers yes, it signs the verifier's fresh random nonce with a per-device secret, so the answer can't be replayed:

$$
\text{proof} = \text{HMAC}\big(k_{\text{device}},\ \texttt{"kagi-nano-v1|id|scope|nonce"}\big)
$$

Wrong guesses are counted in EEPROM, so unplugging the key doesn't reset the rate limit. For one-account-per-person, our central server stores only opaque per-site marks, $\text{scrypt}(\text{HMAC}(\text{pepper}, \text{site} \,\|\, \text{person}))$, and deletes each sign-up session as soon as the website collects its result.

On top of that we built a central sign-up server, demo websites (including Blindgram), a video-call challenge site, a desktop app and an Android app that talks to the PC over Bluetooth.

We built all of this by collaborating closely with AI. Several different agents played critical roles, but **Claude** played an especially critical one. It one-shot many of our demo features and let us build far more than we ever thought we could in a weekend. It even did a large part of our video editing. Watching Claude operate a mobile device to test a UI it had designed was jaw-dropping.

## Challenges we ran into

Our biggest challenge was building a **physical key that any phone can recognize**. We quickly realized RFID/NFC was the only practical option, but we couldn't get it to work with a microcontroller in the time we had. In the end we split our prototype into two parts:

1. **An Arduino Nano** running a faithful recreation of all the hashing, commitment and HMAC logic in about 2 KB of RAM. This shows the security guarantees are achievable on cheap hardware.
2. **A user demo with fixed NFC tags.** It lacks some of those security guarantees, but it's much closer to what a user of the final product would experience: tap your key on your phone, done.

Fitting the cryptography onto the Nano was a challenge of its own. Our desktop prototype uses scrypt, which needs 64 MiB of memory, and the Nano has 2 KiB. We switched to PBKDF2 with fewer iterations and relied on on-chip rate limiting to make up the difference.

## What we learned

- Privacy and verification aren't opposites. A yes/no answer is almost always all a verifier actually needs.
- How much a system leaks by its *shape*, not just its contents. That's why unmet age thresholds had to be indistinguishable decoys rather than empty slots.
- The gap between "cryptographically sound" and "works when you tap it on a phone" is where most of the engineering lives.
- Working with AI agents changes what a small team can attempt in 36 hours.

## What's next

Getting the full cryptography onto a secure NFC chip, so the key a user taps is the same key that holds the guarantees, and replacing the central server's linkable sign-up flow with our blind-signature protocol, so not even the server can connect accounts to people.

---

*A note on this write-up: Claude helped format this post too. Our original draft was, frankly, a typo-riddled mess ("physcial", "protyope", "encryotjion"...), so Claude reorganized and cleaned it up. The story, the inspiration and the late-night struggles are all ours; Claude just made them readable.*
