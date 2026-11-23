/* Actualisation légère du fil de messagerie (7 s), sans WebSocket.
   Le sondage est un confort : une panne réseau ne casse jamais la page. */
(function () {
    const fil = document.getElementById('ua-chat-fil');
    if (!fil) return;

    const url = fil.dataset.pollUrl;
    const videLabel = fil.dataset.videLabel || '';
    const luLabel = fil.dataset.luLabel || '';
    const envoyeLabel = fil.dataset.envoyeLabel || '';
    const confirmationSuppression = fil.dataset.confirmationSuppression || '';
    const modeleSuppr = document.getElementById('ua-chat-suppr-modele');
    const formulaire = document.getElementById('ua-chat-form');
    const champ = document.getElementById('ua-chat-corps');
    const compteur = document.getElementById('ua-chat-compteur');

    const metAJourCompteur = () => {
        if (!champ || !compteur) return;
        compteur.textContent = champ.value.length + ' / ' + champ.maxLength;
        compteur.classList.toggle(
            'est-plein', champ.value.length >= champ.maxLength * 0.9
        );
    };

    if (champ) {
        metAJourCompteur();
        champ.addEventListener('input', metAJourCompteur);
        // Entrée envoie ; Maj+Entrée garde le retour à la ligne. La validation
        // HTML et le POST restent ceux du formulaire, sans double soumission.
        champ.addEventListener('keydown', (evenement) => {
            if (evenement.key !== 'Enter' || evenement.shiftKey || evenement.isComposing) return;
            if (!champ.value.trim()) return;
            evenement.preventDefault();
            if (!formulaire) return;
            if (typeof formulaire.requestSubmit === 'function') formulaire.requestSubmit();
            else formulaire.submit();
        });
    }

    // Délégation : couvre les messages rendus par Django et ceux ajoutés par
    // le sondage. Le libellé vient du gabarit traduit, jamais du JavaScript.
    if (confirmationSuppression) {
        fil.addEventListener('submit', (evenement) => {
            const form = evenement.target;
            if (!(form instanceof HTMLFormElement)
                || !form.classList.contains('ua-chat-suppr-form')) return;
            evenement.preventDefault();
            if (window.confirm(confirmationSuppression)) form.submit();
        });
    }

    const formule = (message) => {
        const article = document.createElement('article');
        article.className = 'ua-chat-bulle' + (message.mien ? ' mien' : '');

        const corps = document.createElement('p');
        corps.className = 'ua-chat-corps';
        corps.textContent = message.corps;

        const pied = document.createElement('div');
        pied.className = 'ua-chat-pied';

        const meta = document.createElement('span');
        meta.className = 'ua-chat-meta';
        let texteMeta = message.auteur + ' — ' + message.heure;
        if (message.mien) {
            texteMeta += ' · ' + (message.lu ? luLabel : envoyeLabel);
        }
        meta.textContent = texteMeta;
        pied.append(meta);

        // Le bouton vient du gabarit : libellés traduits et jeton CSRF inclus.
        if (message.delete_url && modeleSuppr) {
            const formuleSuppr = modeleSuppr.content.firstElementChild.cloneNode(true);
            formuleSuppr.action = message.delete_url;
            pied.append(formuleSuppr);
        }

        article.append(corps, pied);
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
