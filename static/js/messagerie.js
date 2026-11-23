/* Actualisation légère du fil de messagerie (7 s), sans WebSocket.
   Le sondage est un confort : une panne réseau ne casse jamais la page. */
(function () {
    const fil = document.getElementById('ua-chat-fil');
    if (!fil) return;

    const url = fil.dataset.pollUrl;
    const videLabel = fil.dataset.videLabel || '';

    const formule = (message) => {
        const article = document.createElement('article');
        article.className = 'ua-chat-bulle' + (message.mien ? ' mien' : '');

        const corps = document.createElement('p');
        corps.className = 'ua-chat-corps';
        corps.textContent = message.corps;

        const meta = document.createElement('span');
        meta.className = 'ua-chat-meta';
        meta.textContent = message.auteur + ' — ' + message.heure;

        article.append(corps, meta);
        return article;
    };

    const actualise = async () => {
        try {
            const reponse = await fetch(url, { credentials: 'same-origin' });
            if (!reponse.ok) return;
            const donnees = await reponse.json();
            if (donnees.signature === fil.dataset.signature) return;
            fil.dataset.signature = donnees.signature;
            fil.replaceChildren(...(donnees.messages.length
                ? donnees.messages.map(formule)
                : [Object.assign(document.createElement('p'), {
                    className: 'ua-chat-vide',
                    textContent: videLabel,
                })]));
            fil.scrollTop = fil.scrollHeight;
        } catch (e) {
            // Silence volontaire : le formulaire reste utilisable.
        }
    };

    fil.scrollTop = fil.scrollHeight;
    setInterval(actualise, 7000);
})();
