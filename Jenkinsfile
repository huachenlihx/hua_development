pipeline {
    agent any

    environment {
        PYTHON_VERSION = '3.11'
        PDF_INPUT      = 'converts/c3_algorithm.pdf'
        VENV_DIR       = 'venv'
    }

    stages {

        stage('Checkout') {
            steps {
                // Jenkins clones your GitHub repo here automatically.
                // Make sure the repo URL is configured in the Jenkins job.
                checkout scm
                echo "Checked out branch: ${env.GIT_BRANCH}"
            }
        }

        stage('Set Up Python Environment') {
            steps {
                dir('python_test') {
                    sh '''
                        python3 -m venv ${VENV_DIR}
                        . ${VENV_DIR}/bin/activate
                        pip install --upgrade pip
                        pip install -r requirements.txt
                    '''
                }
            }
        }

        stage('Lint') {
            steps {
                dir('python_test') {
                    sh '''
                        . ${VENV_DIR}/bin/activate
                        pip install --quiet flake8
                        flake8 pdf2md.py --max-line-length=120 --extend-ignore=E221,E251,E272 --count --statistics
                    '''
                }
            }
        }

        stage('Convert PDF → Markdown') {
            steps {
                dir('python_test') {
                    sh '''
                        . ${VENV_DIR}/bin/activate
                        python pdf2md.py ${PDF_INPUT} --verbose
                    '''
                }
            }
        }

        stage('Archive Output') {
            steps {
                // Archive the generated .md file and any extracted images
                archiveArtifacts artifacts: 'python_test/converts/*.md',
                                 fingerprint: true,
                                 allowEmptyArchive: false

                archiveArtifacts artifacts: 'python_test/converts/*.jpg, python_test/converts/*.png, python_test/converts/*.jp2',
                                 fingerprint: false,
                                 allowEmptyArchive: true
            }
        }
    }

    post {
        success {
            echo "PDF converted successfully. Check the Artifacts tab for the .md output."
        }
        failure {
            echo "Build failed. Check the Console Output for details."
        }
        always {
            // Clean the workspace after each build to keep Docker container tidy
            cleanWs()
        }
    }
}
