"""Part de 30 % des paiements validés affichée par formateur.

Les montants sont des indicateurs de pilotage : aucun paiement, aucune écriture
de caisse et aucun modèle de paie n'est créé par ces écrans.
"""
from django.urls import reverse
from django.utils import timezone

from core.models import Payment, RoleKey
from core.tests.base import BusinessTestBase
from core.utils import part_salaire_formateur, salaire_formateur, salaires_formateurs


class SalaireFormateurTests(BusinessTestBase):
    def paiement(self, montant, *, statut=Payment.Status.COMPLETED, cle='salaire-test'):
        return Payment.objects.create(
            enrollment=self.enrollment,
            amount=montant,
            currency='XAF',
            method=Payment.Method.CASH,
            status=statut,
            submission_key=cle,
            paid_at=timezone.now(),
        )

    def test_part_30_pourcent_arrondie_a_l_unite(self):
        self.assertEqual(part_salaire_formateur(0), 0)
        self.assertEqual(part_salaire_formateur(100000), 30000)
        self.assertEqual(part_salaire_formateur(100001), 30000)
        self.assertEqual(part_salaire_formateur(100005), 30002)

    def test_seuls_les_paiements_valides_comptent(self):
        self.paiement(100000, cle='salaire-ok')
        self.paiement(50000, statut=Payment.Status.PENDING, cle='salaire-attente')
        self.paiement(50000, statut=Payment.Status.CANCELLED, cle='salaire-annule')
        self.paiement(50000, statut=Payment.Status.REFUNDED, cle='salaire-rembourse')

        resultat = salaire_formateur(self.formateur)
        self.assertEqual(resultat['payments_total'], 100000)
        self.assertEqual(resultat['salary'], 30000)

    def test_groupe_partage_par_deux_formateurs_compte_pour_chacun(self):
        confrere = self.make_user(RoleKey.FORMATEUR, 'confrere@test.local')
        self.session.formateurs.add(confrere)
        self.paiement(100000, cle='salaire-partage')

        lignes = {ligne['formateur'].id: ligne for ligne in salaires_formateurs()}
        for formateur in (self.formateur, confrere):
            with self.subTest(formateur=formateur.email):
                self.assertEqual(lignes[formateur.id]['sessions'], 1)
                self.assertEqual(lignes[formateur.id]['students'], 1)
                self.assertEqual(lignes[formateur.id]['payments_total'], 100000)
                self.assertEqual(lignes[formateur.id]['salary'], 30000)

    def test_formateur_sans_paiement_affiche_zero(self):
        sans_groupe = self.make_user(RoleKey.FORMATEUR, 'sans-groupe@test.local')
        lignes = {ligne['formateur'].id: ligne for ligne in salaires_formateurs()}
        self.assertEqual(lignes[sans_groupe.id]['payments_total'], 0)
        self.assertEqual(lignes[sans_groupe.id]['salary'], 0)
        self.assertEqual(lignes[sans_groupe.id]['sessions'], 0)

    def test_page_reservee_a_la_direction_et_a_la_comptabilite(self):
        url = reverse('core:dashboard:trainer-salaries')
        for user in (self.direction, self.assistant, self.admin, self.super_admin):
            with self.subTest(user=user.email):
                self.assertEqual(self.client_for(user).get(url).status_code, 200)
        for user in (self.formateur, self.etudiant, self.secretaire, self.peda):
            with self.subTest(user=user.email):
                self.assertEqual(self.client_for(user).get(url).status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_page_affiche_chaque_formateur_et_sa_part(self):
        self.paiement(100000, cle='salaire-page')
        page = self.client_for(self.direction).get(
            reverse('core:dashboard:trainer-salaries'))

        self.assertContains(page, 'Salaires des formateurs')
        self.assertContains(page, self.formateur.email)
        self.assertContains(page, '100000')
        self.assertContains(page, '30000')
        self.assertContains(page, '30 %')

    def test_formateur_voit_sa_propre_part_sur_son_tableau_de_bord(self):
        self.paiement(100000, cle='salaire-dashboard')
        page = self.client_for(self.formateur).get(
            reverse('core:dashboard:formateur-dashboard'))

        self.assertContains(page, 'Votre part estimée')
        self.assertContains(page, '30000')
